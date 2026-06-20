# `cctx init` — SessionEnd Hook Installer

**Date:** June 10, 2026  
**Phase:** M19 — Hook installer  
**Author:** cctx team  
**Status:** Approved for implementation

---

## 1. Overview

`cctx init` is an opt-in command that installs a Claude Code [`SessionEnd` hook](https://code.claude.com/docs/en/hooks.md#sessionend) to automate forensic diagnostics. When a Claude Code session ends, the hook runs `cctx autopsy --latest --quiet` and prints a one-line verdict **only when findings exist**. This eliminates the adoption friction of remembering to run cctx manually while preserving the forensic-first principle: output appears only when something went sideways.

### Why SessionEnd, not Stop?

The specification uses `SessionEnd` (session termination), not `Stop` (turn completion). `Stop` fires after every Claude response in every turn, which would trigger autopsy dozens of times per session and pollute output. `SessionEnd` fires exactly once when the session terminates (via `/clear`, `/resume`, logout, or session exit), which is the right moment for a post-mortem. See [Reason](#reason-field) for why the hook doesn't block hard exits (ctrl-C, terminal close).

---

## 2. Hook Configuration

### 2.1 Hook Event Schema

The hook is registered under the `SessionEnd` event in Claude Code's settings with no matcher (all SessionEnd events trigger it). The schema is:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CCTX_INSTALL_COMMAND}",
            "async": true
          }
        ]
      }
    ]
  }
}
```

**Key decisions:**

1. **No matcher**: `SessionEnd` hooks don't support matchers (or if they do, matchers are silently ignored per the [official schema](https://code.claude.com/docs/en/hooks.md#sessionend)). The hook runs for every session end reason.

2. **`async: true`**: The hook must not block session exit. If a hook times out or fails, the session should terminate immediately. `async: true` ensures cctx runs in the background.

3. **`command` syntax**: Reference the cctx binary by absolute path or by relying on `PATH`. The installer resolves the path at write time.

### 2.2 Settings File Target

Depending on the CLI flag, write to:

- **`.claude/settings.json`** (project scope, default): Shared with the team, committed to git, applied only within the project.
- **`~/.claude/settings.json`** (user scope, via `--global` flag): User-local, applies to all projects, never committed.

**Note on scope merging:** Per the [settings reference](https://code.claude.com/docs/en/settings.md#merging-priority), hooks defined at multiple scopes **merge** — both the user and project hooks are active. If both define a `SessionEnd` hook, Claude Code executes both.

### 2.3 Command Form

Use **shell form** (no `args` field) so the command can invoke `cctx` and pipe output cleanly:

```json
{
  "type": "command",
  "command": "cctx autopsy --latest --quiet",
  "async": true
}
```

**Why shell form:** We need the full command-line invocation with flags. Shell form evaluates PATH and allows flagged subcommands; exec form requires `args` and would split the invocation into clunky `["cctx", "autopsy", "--latest", "--quiet"]` pieces.

---

## 3. Idempotency and Hook Preservation

The `cctx init` command must be **idempotent**: running it twice does not duplicate the hook or corrupt existing settings.

### 3.1 Fingerprinting

The hook carries a deterministic fingerprint so `cctx init` can detect whether it's already installed:

```
# Fingerprint: cctx:SessionEnd:autopsy:latest:quiet
```

Place this as a JSON comment or structured marker within the hook configuration that allows the installer to detect the hook even if the exact command string varies slightly (e.g., different cctx paths).

**Implementation:** Use a `description` field (if supported) or embed a stable key in the command string that `cctx init` can grep for and recognize:

```json
{
  "type": "command",
  "command": "cctx autopsy --latest --quiet",
  "async": true,
  "description": "cctx SessionEnd hook (diagnostics on session exit)"
}
```

The installer searches for the presence of `"description": "cctx SessionEnd"` in the hooks array. If found, assume the hook is installed and skip writing (unless `--force` is passed).

### 3.2 Merge Existing Settings

Never overwrite or truncate the entire settings file. Use a JSON-aware merge:

1. Read the target settings file (if it exists; create an empty `{}` if it doesn't).
2. Ensure `hooks` and `hooks.SessionEnd` array structures exist.
3. Append the hook to the `hooks.SessionEnd` array (after checking the fingerprint).
4. Write the merged structure back.

This preserves all existing permissions, models, status line configs, plugins, etc.

### 3.3 Removal (`--remove` flag)

Implement `cctx init --remove` to cleanly uninstall:

1. Read the target settings file.
2. Search the `hooks.SessionEnd` array for the hook with the matching fingerprint.
3. Remove that entry from the array.
4. If the `hooks.SessionEnd` array becomes empty, delete the `SessionEnd` key (and optionally the `hooks` key if empty).
5. Write the updated settings back.

---

## 4. The `--quiet` Mode on Autopsy

A new `--quiet` flag on `cctx autopsy` emits:

- **One-line verdict** when findings exist (e.g., `"3 findings: retry_loop, stale_context, scope_creep"`)
- **Nothing (exit 0)** when the session is clean

The verdict line must be concise and actionable, showing the count and categories of findings without verbose detail. This enables forensic-first: output only when something went wrong, reducing noise in session output.

### 4.1 Implementation Notes

- `--quiet` implies non-interactive output (no spinner, no progress bars).
- Exit code 0 for both clean and dirty sessions (don't fail the session exit).
- The verdict is printed to stdout; errors/warnings go to stderr (so they don't pollute the verdict).
- Works with other flags like `--since` for cross-session analysis in a quiet mode.

---

## 5. Hook Behavior and Gotchas

### 5.1 Does SessionEnd Fire on Hard Exits?

Per the [official documentation](https://code.claude.com/docs/en/hooks.md#sessionend), SessionEnd fires when:

- User runs `/clear` command (clean)
- User switches sessions via `/resume` (clean)
- User logs out (clean)
- User exits during prompt input (clean)
- Bypass permissions mode is disabled (clean)
- "Other" exit reasons (catch-all)

**Key limitation:** The documentation lists five specific end reasons and does not include hard exits (Ctrl-C, terminal close, crash, SIGTERM). This means:

- If the user force-quits Claude Code (Ctrl-C), the SessionEnd hook may not fire.
- If the terminal is closed, the hook may not fire.
- The hook is best-effort for cleanup; it should not be relied upon for critical session tracking.

**Design implication:** Document this in PRODUCT.md and the user-facing help. The hook is for "diagnostic snapshots after normal session exit," not for catching all terminations. This is acceptable because the session log (`~/.claude/projects/<id>.jsonl`) is written continuously and independently; the hook just surfaces findings, not records the session.

### 5.2 Timeout and Non-Blocking Semantics

Per the documentation, SessionEnd hooks have a **default timeout of 1.5 seconds**. If cctx takes longer, it is killed.

**Design decision:** Accept the 1.5s default. For a `--quiet` autopsy on a recent session, 1.5s is sufficient (parse log + run heuristics + print one line). If it times out, the session still exits cleanly—there's no visible failure to the user (the hook runs `async`).

**Caveat:** If the user has a very large session or a slow disk, the hook might time out silently. This is acceptable because:
- `--quiet` mode is opt-in.
- cctx is a diagnostic, not critical path.
- Silent timeout is better than blocking session exit.

If users report timeouts, a future enhancement can:
- Make the timeout configurable in the hook's `timeout` field.
- Pre-compile the session log parsing for speed.

### 5.3 Error Handling

SessionEnd hooks have **no decision control**—they cannot block or modify session termination. If the hook fails (non-zero exit, timeout, command not found), the session exits normally and the error is logged but not shown to the user (running async).

**Implementation:** Wrap the command in a shell script that:
1. Sets `set -e` or checks exit codes.
2. Redirects stderr to `/dev/null` (suppress errors).
3. Logs failures to a file if needed (cctx's own logging, not user-visible).

Example:

```bash
#!/bin/bash
# ~/.claude/hooks/cctx-sessionend.sh
# Suppress errors; don't block session exit
cctx autopsy --latest --quiet 2>/dev/null || true
```

But for the initial release, inline the command directly in settings.json. If failures become an issue, move to a wrapper script.

---

## 6. Command Interface

### 6.1 `cctx init` — Install Hook (Default)

```bash
cctx init                    # Install to .claude/settings.json (project scope)
cctx init --global           # Install to ~/.claude/settings.json (user scope)
cctx init --global --remove  # Uninstall from user scope
cctx init --force            # Reinstall even if hook is already present
```

### 6.2 Output

```
$ cctx init
✓ SessionEnd hook installed to .claude/settings.json
  Run 'cctx init --remove' to uninstall.

$ cctx init --global
✓ SessionEnd hook installed to ~/.claude/settings.json
  Run 'cctx init --global --remove' to uninstall.

$ cctx init
! SessionEnd hook already installed in .claude/settings.json
  Use 'cctx init --force' to reinstall.

$ cctx init --remove
✓ SessionEnd hook removed from .claude/settings.json
```

### 6.3 Edge Cases

- **No `.claude/` directory**: Create it (it should exist if Claude Code has been used).
- **Invalid JSON in settings file**: Error loudly; don't corrupt it.
- **Both project and user hooks installed**: Both are active. `cctx init --remove` removes only the target scope.
- **`--force --remove`**: Ambiguous; error with help text.

---

## 7. Acceptance Criteria

- [x] **Spec approved** — This document reviewed by the team.
- [ ] `cctx init` command implemented in `cctx/cli.py`.
- [ ] Hook configuration written to `.claude/settings.json` or `~/.claude/settings.json` with proper merge logic.
- [ ] Idempotency: running `cctx init` twice does not duplicate the hook.
- [ ] `cctx init --remove` cleanly uninstalls.
- [ ] `cctx init --global` writes to user scope.
- [ ] `cctx autopsy --quiet` emits one-line verdict (findings exist) or nothing (clean).
- [ ] SessionEnd hook runs asynchronously; does not block session exit.
- [ ] Hook error handling: silent failure on timeout/error.
- [ ] Tests:
  - Idempotency (run twice, hook appears once).
  - Settings merge (preserve existing permissions/hooks).
  - Removal (hook gone after `--remove`).
  - Quiet mode output on clean/dirty fixtures.
  - Global vs. project scope.
  - Invalid JSON handling.

---

## 8. Risk & Mitigation

| Risk | Mitigation |
|------|-----------|
| Hook doesn't fire on hard exits (Ctrl-C). | Document as best-effort. Session log is still written independently. |
| Hook times out (1.5s default). | Acceptable for `--quiet` mode; silent failure in background. Future: make configurable. |
| Hook breaks settings JSON if merge logic is buggy. | Use a tested JSON library (standard `json` module in Python). Write comprehensive tests. |
| User installs hook, then disables cctx or uninstalls it → hook fails silently on every session end. | Hook runs async; silent failure is acceptable. User can uninstall with `cctx init --remove`. |
| Multiple teams' cctx processes writing to same `.claude/settings.json` concurrently. | Use atomic file operations (write to temp file, then rename). OR document as single-user only (typical). |

---

## 9. Future Enhancements

1. **Configurable verdict format** — allow `--verdict-format json` for programmatic consumption.
2. **Emoji/color in verdict** — make the one-liner more visually distinct.
3. **Custom hook script** — `cctx init --script /path/to/script.sh` to run a custom hook instead.
4. **Timeout override** — `cctx init --timeout 5000` to set a longer timeout.
5. **Cross-agent emission** — emit findings as `.cursorrules`, `AGENTS.md`, or Copilot instructions (separate feature; M20+).

---

## 10. References

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks.md)
- [Claude Code Settings Reference](https://code.claude.com/docs/en/settings.md)
- [cctx PRODUCT.md — Forensic-first principle](#)
- [Issue #92: `cctx init` — opt-in SessionEnd hook installer](https://github.com/anthropics/cctx/issues/92)
