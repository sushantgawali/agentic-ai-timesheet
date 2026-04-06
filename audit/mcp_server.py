#!/usr/bin/env python3
"""
Subprocess MCP server — exposes the three audit tools over stdio.

Spawned by audit_agent_sdk.py via ClaudeAgentOptions mcp_servers config.
Runs for the lifetime of the Claude Code CLI session, maintaining
_results state between tool calls.
"""
import json
import os
import sys

# Ensure project root is on the path (this script is run as a subprocess)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from audit.checks import run_all
from audit.loader import load_all
from audit.report import generate

app = Server("audit-tools")

# State shared between tool calls within a single session
_results: dict = {}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="load_timesheet_data",
            description=(
                "Load all CSV source files (timesheets, HR, projects, Slack, Git) "
                "from the data directory and return a loading summary."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="run_audit_checks",
            description=(
                "Run all 13 audit checks against the loaded data. "
                "Stores results internally. Returns a findings summary and the top issues. "
                "Call load_timesheet_data first."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="generate_html_report",
            description=(
                "Write the HTML audit report to the output directory and return the file path. "
                "Uses results stored by run_audit_checks — call that first. "
                "Pass key_takeaways_json as a JSON-encoded array of 3-5 concise insight "
                "strings to display in the report below the summary tiles. "
                "Example: '[\"admin and bob billed an archived project.\", \"john has overlapping entries.\"]'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key_takeaways_json": {
                        "type": "string",
                        "description": (
                            "JSON-encoded array of 3-5 insight strings. "
                            "Example: '[\"Insight one.\", \"Insight two.\"]'"
                        ),
                    }
                },
                "required": [],  # optional — report is still generated without it
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    def ok(data: dict) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data))]

    def err(msg: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"error": msg}))]

    try:
        if name == "load_timesheet_data":
            ctx = load_all()
            return ok({
                "status": "loaded",
                "summary": {
                    "timesheet_rows":      len(ctx["ts"]),
                    "employees":           len(ctx["emp_rate"]),
                    "projects":            len(ctx["proj_status"]),
                    "approved_leave_days": len(ctx["approved_leave"]),
                    "active_slack_days":   len(ctx["slack_active"]),
                    "active_git_days":     len(ctx["git_active"]),
                },
            })

        elif name == "run_audit_checks":
            issues, hours_issues = run_all()
            ctx = load_all()
            _results["issues"]        = issues
            _results["hours_issues"]  = hours_issues
            _results["total_entries"] = len(ctx["ts"])

            n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
            n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
            n_info = sum(1 for i in issues if i["severity"] == "INFO")
            top = [
                {
                    "check": i["check"], "label": i["label"],
                    "user":  i["user"],  "date":  i["date"], "brief": i["brief"],
                }
                for i in issues[:20]
            ]
            return ok({
                "summary": {
                    "total_entries": len(ctx["ts"]),
                    "total_issues":  len(issues),
                    "critical": n_crit,
                    "warning":  n_warn,
                    "info":     n_info,
                },
                "top_issues": top,
            })

        elif name == "generate_html_report":
            if not _results:
                return err("run_audit_checks must be called first")

            raw = arguments.get("key_takeaways_json", "[]") or "[]"
            try:
                takeaways = json.loads(raw)
                if not isinstance(takeaways, list):
                    takeaways = [str(takeaways)]
            except Exception:
                takeaways = [raw] if raw != "[]" else []

            path = generate(
                issues=_results["issues"],
                hours_issues=_results["hours_issues"],
                total_entries=_results["total_entries"],
                key_takeaways=takeaways,
            )
            return ok({"status": "written", "path": path})

        else:
            return err(f"Unknown tool: {name}")

    except Exception as exc:
        return err(str(exc))


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)
