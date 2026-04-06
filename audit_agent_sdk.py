#!/usr/bin/env python3
"""
Timesheet audit agent — Agent SDK entry point.

Uses claude-agent-sdk with custom in-process MCP tools so the Agent SDK
orchestrates the audit loop instead of a manual Claude API tool loop.

Requires:
    pip install claude-agent-sdk
    npm install -g @anthropic-ai/claude-code   (Claude Code CLI)

Required env var: ANTHROPIC_API_KEY
Optional env vars: DATA_DIR (default: data), OUT_DIR (default: output)
"""
import json
import os
import sys
import anyio

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from audit.checks import run_all
from audit.loader import load_all
from audit.report import generate

# ---------------------------------------------------------------------------
# Module-level state — shared between tool calls within a single run
# ---------------------------------------------------------------------------
_results: dict = {}


# ---------------------------------------------------------------------------
# MCP tools — the core audit logic exposed as Agent SDK tools
# ---------------------------------------------------------------------------

@tool(
    "load_timesheet_data",
    "Load all CSV source files (timesheets, HR, projects, Slack, Git) "
    "from the data directory and return a loading summary.",
    {},
)
async def tool_load_data(args: dict) -> dict:
    try:
        ctx = load_all()
        summary = {
            "timesheet_rows":      len(ctx["ts"]),
            "employees":           len(ctx["emp_rate"]),
            "projects":            len(ctx["proj_status"]),
            "approved_leave_days": len(ctx["approved_leave"]),
            "active_slack_days":   len(ctx["slack_active"]),
            "active_git_days":     len(ctx["git_active"]),
        }
        return {"content": [{"type": "text", "text": json.dumps({"status": "loaded", "summary": summary})}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}]}


@tool(
    "run_audit_checks",
    "Run all 13 audit checks against the loaded data. "
    "Stores results internally. Returns a findings summary and the top issues. "
    "Call load_timesheet_data first.",
    {},
)
async def tool_run_checks(args: dict) -> dict:
    try:
        issues, hours_issues = run_all()
        ctx = load_all()

        # Store for generate_html_report
        _results["issues"]        = issues
        _results["hours_issues"]  = hours_issues
        _results["total_entries"] = len(ctx["ts"])

        n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
        n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
        n_info = sum(1 for i in issues if i["severity"] == "INFO")

        top = [
            {
                "check": i["check"],
                "label": i["label"],
                "user":  i["user"],
                "date":  i["date"],
                "brief": i["brief"],
            }
            for i in issues[:20]
        ]
        return {"content": [{"type": "text", "text": json.dumps({
            "summary": {
                "total_entries": len(ctx["ts"]),
                "total_issues":  len(issues),
                "critical": n_crit,
                "warning":  n_warn,
                "info":     n_info,
            },
            "top_issues": top,
        })}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}]}


@tool(
    "generate_html_report",
    "Write the HTML audit report to the output directory and return the file path. "
    "Uses results stored by run_audit_checks. Call run_audit_checks first. "
    "Pass key_takeaways_json as a JSON array string of 3-5 concise insight strings "
    "to display in the report below the summary tiles. "
    'Example: \'["Insight one.", "Insight two."]\' ',
    {"key_takeaways_json": str},
)
async def tool_generate_report(args: dict) -> dict:
    try:
        if not _results:
            return {"content": [{"type": "text", "text": json.dumps(
                {"error": "run_audit_checks must be called first"}
            )}]}
        import json as _json
        raw = args.get("key_takeaways_json", "[]")
        try:
            takeaways = _json.loads(raw) if raw else []
        except Exception:
            takeaways = [raw] if raw else []
        path = generate(
            issues=_results["issues"],
            hours_issues=_results["hours_issues"],
            total_entries=_results["total_entries"],
            key_takeaways=takeaways,
        )
        return {"content": [{"type": "text", "text": json.dumps({"status": "written", "path": path})}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}]}


# ---------------------------------------------------------------------------
# Main — wire up the in-process MCP server and run the agent
# ---------------------------------------------------------------------------

async def main() -> None:
    mcp_server = create_sdk_mcp_server(
        "audit-tools",
        tools=[tool_load_data, tool_run_checks, tool_generate_report],
    )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-6",
        mcp_servers={"audit": mcp_server},
        permission_mode="bypassPermissions",
        max_turns=10,
    )

    print("[audit-agent-sdk] Starting...", flush=True)

    async for message in query(
        prompt=(
            "Run a full timesheet audit: "
            "1. Load all source data. "
            "2. Run all audit checks. "
            "3. Call generate_html_report with key_takeaways_json set to a "
            "JSON array string of 3-5 concise, specific insights about the "
            "most important patterns found (who is affected, likely root cause, "
            'what needs urgent attention). Example value: \'["Insight 1.", "Insight 2."]\'. '
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


if __name__ == "__main__":
    try:
        anyio.run(main)
    except Exception as e:
        # The Agent SDK raises when the CLI exits non-zero, which can happen
        # even after a successful run (e.g. MCP server teardown). Treat it as
        # success if the report file was actually written.
        from datetime import date as _date
        today = _date.today().isoformat()
        report = os.path.join(os.environ.get("OUT_DIR", "output"), f"audit_{today}.html")
        if "Command failed" in str(e) and os.path.exists(report):
            print(f"[audit-agent-sdk] Report written to {report}", flush=True)
            sys.exit(0)
        print(f"[audit-agent-sdk] Fatal: {e}", file=sys.stderr)
        sys.exit(1)
