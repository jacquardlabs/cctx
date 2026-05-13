#!/usr/bin/env python3
"""Anonymize a Claude Code session JSONL + sibling dirs for use as test fixtures.

Usage:
    python tests/fixtures/scrub.py <source-jsonl-path> <destination-slug>

Output: tests/fixtures/claude_code/<slug>/ with:
  - <slug>.jsonl (anonymized main transcript)
  - <slug>/subagents/agent-*.jsonl (if present, anonymized)
  - <slug>/subagents/agent-*.meta.json (if present, copied verbatim)
  - <slug>/tool-results/*.txt (if present, truncated to 1KB max)

Transformations:
- Replace /Users/<name>/ paths with /Users/test/
- Replace home dirs in any string field via regex
- Truncate toolUseResult.file.content > 200 chars
- Truncate tool_result.content blocks > 500 chars
- Scrub git branch names to "test-branch"
- Replace any value of a key matching /api_key|apikey|secret|token|password|auth/i with "[SCRUBBED]"
- Preserve all structural shapes (types, keys, list lengths)
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

_HOME_PATH = re.compile(r"/Users/[^/\"\s]+")
_FIXTURES_ROOT = Path(__file__).parent / "claude_code"

_SENSITIVE_KEYS = re.compile(r"api[_-]?key|secret|token|password|auth", re.IGNORECASE)
# Match environment variable names and actual secret patterns
_SECRET_PATTERNS = [
    re.compile(r"ANTHROPIC_API_KEY", re.IGNORECASE),  # Env var name
    re.compile(r"ANTHROPIC_KEY", re.IGNORECASE),  # Env var name
    re.compile(r"GOOGLE_CLIENT_ID", re.IGNORECASE),  # Google OAuth var names
    re.compile(r"GOOGLE_CLIENT_SECRET", re.IGNORECASE),  # Google OAuth var names
    re.compile(r"(sk-[a-zA-Z0-9]+)", re.IGNORECASE),  # OpenAI/Anthropic key patterns
    re.compile(r"(Bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"(CLIENT_SECRET|CLIENT_ID)\s*[=:]\s*['\"]?[a-zA-Z0-9_\-\.]+['\"]?", re.IGNORECASE),
    # OAuth API endpoint references like api03-xyz
    re.compile(r"api\d+-[a-zA-Z0-9]+", re.IGNORECASE),
    # Google OAuth domains
    re.compile(r"[a-zA-Z0-9]+\.apps\.googleusercontent\.com", re.IGNORECASE),
]


def _walk(obj, parent=None, key=None):
    """Iterate (parent, key_or_index, value) tuples for every node."""
    yield parent, key, obj
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            yield from _walk(v, obj, k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, obj, i)


def anonymize_line(obj: dict) -> dict:
    out = json.loads(json.dumps(obj))

    if "cwd" in out and isinstance(out["cwd"], str):
        out["cwd"] = _HOME_PATH.sub("/Users/test", out["cwd"])
    if out.get("gitBranch") not in (None, "HEAD"):
        out["gitBranch"] = "test-branch"

    # Walk and transform every node.
    for parent, key, value in list(_walk(out)):
        if parent is None or key is None:
            continue
        # Sensitive keys → SCRUBBED.
        if isinstance(key, str) and _SENSITIVE_KEYS.search(key):
            parent[key] = "[SCRUBBED]"
            continue
        if isinstance(value, str):
            new_value = _HOME_PATH.sub("/Users/test", value)
            # Redact secret patterns in string content
            for pattern in _SECRET_PATTERNS:
                new_value = pattern.sub("[SCRUBBED]", new_value)
            parent[key] = new_value

    # Targeted truncations.
    for _parent, key, value in list(_walk(out)):
        if isinstance(value, dict) and key == "file":
            content = value.get("content")
            if isinstance(content, str) and len(content) > 200:
                value["content"] = content[:200] + "...[truncated]"
        if isinstance(value, dict) and value.get("type") == "tool_result":
            c = value.get("content")
            if isinstance(c, str) and len(c) > 500:
                value["content"] = c[:500] + "...[truncated]"

    return out


def anonymize_jsonl(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            fout.write(json.dumps(anonymize_line(obj)) + "\n")


def anonymize_session(src_jsonl: Path, slug: str) -> Path:
    dst_dir = _FIXTURES_ROOT / slug
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)

    # Main transcript.
    anonymize_jsonl(src_jsonl, dst_dir / f"{slug}.jsonl")

    # Sibling dirs.
    src_sibling = src_jsonl.parent / src_jsonl.stem
    if src_sibling.is_dir():
        sub_dst_root = dst_dir / slug
        # subagents/
        sub_src = src_sibling / "subagents"
        if sub_src.is_dir():
            sub_dst = sub_dst_root / "subagents"
            for sub_jsonl in sub_src.glob("*.jsonl"):
                anonymize_jsonl(sub_jsonl, sub_dst / sub_jsonl.name)
            for meta in sub_src.glob("*.meta.json"):
                (sub_dst / meta.name).parent.mkdir(parents=True, exist_ok=True)
                (sub_dst / meta.name).write_text(meta.read_text())
        # tool-results/
        tr_src = src_sibling / "tool-results"
        if tr_src.is_dir():
            tr_dst = sub_dst_root / "tool-results"
            tr_dst.mkdir(parents=True, exist_ok=True)
            for f in tr_src.glob("*.txt"):
                raw = f.read_text(encoding="utf-8", errors="replace")
                sanitized = _HOME_PATH.sub("/Users/test", raw)
                if len(sanitized) > 1024:
                    sanitized = sanitized[:1024] + "\n...[truncated]"
                (tr_dst / f.name).write_text(sanitized, encoding="utf-8")

    return dst_dir


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1
    src = Path(sys.argv[1]).expanduser().resolve()
    slug = sys.argv[2]
    if src.is_dir():
        src = src.parent / f"{src.name}.jsonl"
    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        return 1
    dst = anonymize_session(src, slug)
    print(f"anonymized -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
