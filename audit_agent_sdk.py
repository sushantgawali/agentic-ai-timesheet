#!/usr/bin/env python3
"""
Timesheet audit agent — Agent SDK entry point.

Uses claude-agent-sdk with a subprocess MCP server (audit/mcp_server.py)
that exposes the three audit tools over stdio. The Agent SDK + Claude Code
CLI orchestrate the tool loop; the MCP server contains all audit logic.

Requires:
    pip install claude-agent-sdk mcp anyio
    npm install -g @anthropic-ai/claude-code   (Claude Code CLI)

Required env var: ANTHROPIC_API_KEY
Optional env vars: DATA_DIR (default: data), OUT_DIR (default: output)
"""
import os
import sys
import time
import anyio
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    server_script = str(Path(__file__).parent / "audit" / "mcp_server.py")

    options = ClaudeAgentOptions(
        mcp_servers={
            "audit": {
                "type": "stdio",
                "command": "python3",
                "args": [server_script],
                "env": {
                    "DATA_DIR":   os.environ.get("DATA_DIR", "data"),
                    "OUT_DIR":    os.environ.get("OUT_DIR", "output"),
                    "PYTHONPATH": str(Path(__file__).parent),
                },
            }
        },
        permission_mode="bypassPermissions",
        max_turns=10,
    )

    print("[audit-agent-sdk] Starting...", flush=True)

    async for message in query(
        prompt=(
            "Run a full timesheet audit using the audit MCP tools: "
            "1. Call load_timesheet_data. "
            "2. Call run_audit_checks. "
            "3. Analyse the findings, then call generate_html_report passing "
            "key_takeaways_json as a JSON array string of 3-5 concise, specific "
            "insights (who is affected, likely root cause, what needs urgent attention). "
            'Example: \'["admin and bob billed Legacy Migration which is archived.", '
            '"john has overlapping entries on 2026-03-17."]\' '
            "Then print a brief plain-text summary of the findings."
        ),
        options=options,
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)

        elif isinstance(message, ResultMessage):
            cost_usd = getattr(message, "cost_usd", None)
            cost = f" | cost: ${cost_usd:.4f}" if cost_usd else ""
            print(f"\n[audit-agent-sdk] Done{cost}.", flush=True)


def _is_overloaded(e: Exception) -> bool:
    msg = str(e)
    return "529" in msg or "overloaded" in msg.lower()


if __name__ == "__main__":
    from datetime import date as _date

    MAX_RETRIES = 3
    delay = 30  # seconds, doubles each retry

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            anyio.run(main)
            break  # success
        except Exception as e:
            # The Agent SDK raises when the CLI exits non-zero, which can happen
            # even after a successful run (e.g. during MCP server teardown).
            # Treat as success if the report file was actually written.
            today = _date.today().isoformat()
            report = os.path.join(os.environ.get("OUT_DIR", "output"), f"audit_{today}.html")
            if "Command failed" in str(e) and os.path.exists(report):
                print(f"[audit-agent-sdk] Report written to {report}", flush=True)
                sys.exit(0)

            if _is_overloaded(e) and attempt < MAX_RETRIES:
                print(
                    f"[audit-agent-sdk] API overloaded (attempt {attempt}/{MAX_RETRIES}),"
                    f" retrying in {delay}s...",
                    flush=True,
                )
                time.sleep(delay)
                delay *= 2
                continue

            print(f"[audit-agent-sdk] Fatal: {e}", file=sys.stderr)
            sys.exit(1)
