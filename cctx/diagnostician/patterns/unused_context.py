"""Unused-context classifier — MCP servers loaded but never called.

Signal B only: MCP tool names are observable in deferred_tools_delta
attachments; any server whose tools were never invoked across the session
is flagged. One finding per unused server.

Signal A (schema fetched via ToolSearch but not called) is excluded: schema
text is not stored in the JSONL so there is no honest cost basis for it,
and ToolSearch fetches are model-driven — not user-configurable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace


def classify(trace: SessionTrace) -> list[Finding]:
    """Return one Finding per MCP server whose tools were never called."""
    available_mcp: set[str] = set()
    for att in trace.attachments:
        if att.kind == "mcp_servers":
            for name in att.raw.get("addedNames", []):
                if name.startswith("mcp__"):
                    available_mcp.add(name)

    if not available_mcp:
        return []

    called: set[str] = {
        use.tool_name
        for turn in trace.turns
        for use in turn.tool_uses
    }

    # Group available MCP tools by server name (mcp__<server>__<tool>)
    servers: dict[str, list[str]] = {}
    for name in available_mcp:
        parts = name.split("__", 2)
        server = parts[1] if len(parts) >= 2 else "unknown"
        servers.setdefault(server, []).append(name)

    num_turns = len(trace.turns)
    findings: list[Finding] = []

    for server in sorted(servers):
        server_tools = servers[server]
        # Skip if any tool from this server was called — partial use is not waste
        if any(t in called for t in server_tools):
            continue

        findings.append(Finding(
            kind=FindingKind.UNUSED_CONTEXT,
            severity=Severity.LOW,
            confidence=Confidence.MEDIUM,
            first_turn=1,
            last_turn=num_turns or None,
            evidence={
                "mcp_server": server,
                "tools_available": sorted(server_tools),
                "tools_called": [],
            },
            cost_usd=None,
            summary=(
                f"MCP server `{server}` loaded but never called "
                f"({len(server_tools)} tool{'s' if len(server_tools) != 1 else ''} available)"
            ),
        ))

    return findings
