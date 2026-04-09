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
Optional env vars: DATA_DIR (default: data), OUT_DIR (default: output), MODEL (default: claude-haiku-4-5-20251001)
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
    model = os.environ.get("MODEL", "claude-haiku-4-5-20251001")

    options = ClaudeAgentOptions(
        model=model,
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
        max_turns=12,
    )

    print(f"[audit-agent-sdk] Starting with model={model}", flush=True)

    async for message in query(
        prompt=(
            "Run a full timesheet audit using the audit MCP tools: "
            "1. Call discover_data_files to see all CSV files present and their inferred roles. "
            "2. Call read_guidelines_documents to load all HR policy and guideline documents. "
            "   Note the rules around leave types, public holidays, timesheet field requirements, "
            "   and any billing restrictions — use these as the compliance baseline throughout. "
            "3. Call read_sow_documents to load all Statement of Work contracts. "
            "   For each SOW, note the contracted team members, their rates, and monthly hours. "
            "   Cross-reference against the project_actuals returned: identify projects where "
            "   actual hours or cost diverge significantly from contract expectations. "
            "   Also flag if anyone is billing to a project not listed in their SOW team. "
            "4. Call load_timesheet_data to load and index all timesheet data. "
            "5. Call run_audit_checks to execute all audit checks. "
            "6. Analyse the findings (including policy violations from guidelines and SOW "
            "   divergences), then call generate_html_report passing "
            "key_takeaways_json as a JSON array string of 3-5 concise, specific "
            "insights covering: critical billing anomalies, policy violations (referencing "
            "specific guideline rules where relevant), SOW vs actual divergences, "
            "and projects near or over budget. "
            'Example: \'["Entain-CRM is 32% over its contracted hours budget.", '
            '"rishabh.a billed Provus but is not listed in the Provus SOW team.", '
            '"3 employees billed on public holidays contrary to the Holidays guideline."]\' '
            "Then print a brief plain-text summary including guidelines findings, SOW findings, "
            "and budget status."
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
