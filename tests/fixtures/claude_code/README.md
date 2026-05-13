# Claude Code session fixtures

Sanitized real-session JSONLs from `~/.claude/projects/`. Used by the parser test suite to validate parsing against real-world data.

## Sanitization

- `/Users/<name>/` paths replaced with `/Users/test/`.
- Git branches replaced with `test-branch` (HEAD preserved).
- `toolUseResult.file.content` truncated to 200 characters.
- Large `tool_result.content` truncated to 500 characters.
- `tool-results/*.txt` sidecar files truncated to 1KB.
- Sensitive-key values (api_key, token, secret, password, auth) replaced with `[SCRUBBED]`.

## Adding a new fixture

```bash
python tests/fixtures/scrub.py <source.jsonl> <slug>
```

## Current fixtures

| Slug | What it exercises |
|---|---|
| short-clean | 7 lines, no subagents, no sidecars — happy-path smoke test |
| with-subagents | Session with subagent tool calls (Agent) and recursive session parsing |
| with-tool-results | Has offloaded `tool-results/*.txt` sidecar files |
| with-compaction | Session that hit a `SessionStart:compact` hook event |
| with-attachments | Polymorphic attachment shapes (hook output, mcp_servers, skills) with MCP server events |
