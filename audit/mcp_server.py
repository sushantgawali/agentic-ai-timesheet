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
from audit.loader import load_all, discover_csv_files, load_sow_documents, load_guidelines_documents, DATA_VERSION
from audit.report import generate

app = Server("audit-tools")

# State shared between tool calls within a single session
_results: dict = {}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="read_sow_documents",
            description=(
                "Parse all Statement of Work (SOW) DOCX files in the data directory and return "
                "structured data: project name, client, SOW reference, effective/end dates, "
                "contracted monthly value, and team composition (name, role, allocation %, "
                "contractual rate USD/hr, monthly hours commitment). "
                "Use this to cross-reference who should be billing to each project, at what "
                "rate, and for how many hours — then compare against timesheet actuals."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="read_guidelines_documents",
            description=(
                "Parse all HR policy and guideline documents (PDF and DOCX) from the "
                "documents/guidelines/ directory. Returns the filename and full extracted text "
                "for each document. Use this to understand company policies on leave, holidays, "
                "timesheets, and billing rules — then cross-reference against the audit findings "
                "to identify policy violations and include relevant policy context in takeaways."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="discover_data_files",
            description=(
                "Scan the data directory for all CSV files, read their column headers, "
                "and infer each file's semantic role (timesheets, employees, assignments, "
                "leave, projects, slack, git, holidays, calendar_leave, emails, calendar). "
                "Call this first to understand what data is available before loading."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
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
        if name == "read_guidelines_documents":
            docs = load_guidelines_documents()
            return ok({
                "guidelines_count": len(docs),
                "guidelines": [
                    {
                        "filename": d["filename"],
                        "type":     d["type"],
                        "text":     d["text"],
                    }
                    for d in docs
                ],
                "hint": (
                    "Use these policy documents to validate audit findings against company rules. "
                    "E.g. check if leave types match policy, if public holidays align with the "
                    "holidays guideline, and if timesheet fields comply with the timesheets guideline."
                ),
            })

        elif name == "read_sow_documents":
            sow_docs = load_sow_documents()
            ctx = load_all()
            # Attach actuals per project so Claude can compare in one call
            proj_actual_hours = ctx.get("proj_actual_hours", {})
            proj_actual_cost  = ctx.get("proj_actual_cost",  {})
            proj_budget_hours = ctx.get("proj_budget_hours", {})
            proj_budget_cost  = ctx.get("proj_budget_cost",  {})

            enriched = []
            for doc in sow_docs:
                pname = doc.get("project_name", "")
                enriched.append({
                    "filename":       doc["filename"],
                    "project_name":   pname,
                    "client":         doc.get("client"),
                    "sow_reference":  doc.get("sow_reference"),
                    "effective_date": doc.get("effective_date"),
                    "end_date":       doc.get("end_date"),
                    "monthly_value":  doc.get("monthly_value"),
                    "team":           doc.get("team", []),
                    # Best-effort actuals lookup (project name may differ from timesheet)
                    "note": "project_name in SOW may differ from project name used in timesheets",
                })

            return ok({
                "sow_count":          len(sow_docs),
                "sow_documents":      enriched,
                "project_actuals":    {
                    p: {
                        "actual_hours":  round(proj_actual_hours.get(p, 0), 2),
                        "actual_cost":   round(proj_actual_cost.get(p, 0), 2),
                        "budget_hours":  proj_budget_hours.get(p, 0),
                        "budget_cost":   proj_budget_cost.get(p, 0),
                    }
                    for p in sorted(set(proj_budget_hours) | set(proj_actual_hours))
                },
                "hint": (
                    "SOW project names often differ from timesheet project names. "
                    "Use customer/scope context to match them. "
                    "Compare SOW team rates against timesheet hourly_rate values "
                    "and SOW monthly_hours against actual hours logged per user per month."
                ),
            })

        elif name == "discover_data_files":
            files = discover_csv_files()
            return ok({
                "data_dir": os.environ.get("DATA_DIR", "data"),
                "files_found": len(files),
                "files": [
                    {
                        "filename": f["filename"],
                        "columns":  f["columns"],
                        "role":     f["role"],
                    }
                    for f in files
                ],
                "roles_detected": {
                    f["role"]: f["filename"]
                    for f in files if f["role"]
                },
                "unrecognised": [f["filename"] for f in files if not f["role"]],
            })

        elif name == "load_timesheet_data":
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
                    "calendar_events":     len(ctx["calendar"]),
                },
            })

        elif name == "run_audit_checks":
            issues, hours_issues = run_all()
            ctx = load_all()
            _results["issues"]            = issues
            _results["hours_issues"]      = hours_issues
            _results["total_entries"]     = len(ctx["ts"])
            _results["proj_budget_hours"] = ctx.get("proj_budget_hours", {})
            _results["proj_budget_cost"]  = ctx.get("proj_budget_cost",  {})
            _results["proj_actual_hours"] = ctx.get("proj_actual_hours", {})
            _results["proj_actual_cost"]  = ctx.get("proj_actual_cost",  {})

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
                data_version=DATA_VERSION,
                model=os.environ.get("MODEL", "claude-haiku-4-5-20251001"),
                proj_budget_hours=_results.get("proj_budget_hours", {}),
                proj_budget_cost=_results.get("proj_budget_cost",  {}),
                proj_actual_hours=_results.get("proj_actual_hours", {}),
                proj_actual_cost=_results.get("proj_actual_cost",  {}),
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
