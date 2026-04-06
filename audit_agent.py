#!/usr/bin/env python3
"""
Timesheet audit agent — deployable entry point.

Runs inside GitLab CI (or locally) with just:
    pip install anthropic
    python audit_agent.py

Required env var: ANTHROPIC_API_KEY
Optional env vars:
    DATA_DIR   path to CSV directory    (default: data)
    OUT_DIR    path for HTML output     (default: output)
    MODEL      Claude model ID override (default: claude-opus-4-6)
"""
import json
import os
import sys

import anthropic

from audit.checks import run_all
from audit.loader import load_all
from audit.report import generate

# ---------------------------------------------------------------------------
# Tool definitions — what Claude can call
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "load_timesheet_data",
        "description": (
            "Load all CSV source files (timesheets, HR, projects, Slack, Git) "
            "from the data directory. Returns a summary of what was loaded."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_audit_checks",
        "description": (
            "Run all 13 audit checks against the loaded data. "
            "Stores results internally. Returns a summary of findings "
            "(counts by severity and the top issues). "
            "Call load_timesheet_data first."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "generate_html_report",
        "description": (
            "Write the HTML audit report to the output directory and return the file path. "
            "Uses the results stored by run_audit_checks — no inputs needed. "
            "Call run_audit_checks first."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

# Module-level state shared between tools within a single run
_audit_results: dict = {}


# ---------------------------------------------------------------------------
# Tool executor — maps tool name → implementation
# ---------------------------------------------------------------------------
def execute_tool(name: str, inputs: dict) -> str:
    if name == "load_timesheet_data":
        ctx = load_all()
        summary = {
            "timesheet_rows": len(ctx["ts"]),
            "employees": len(ctx["emp_rate"]),
            "projects": len(ctx["proj_status"]),
            "approved_leave_days": len(ctx["approved_leave"]),
            "active_slack_days": len(ctx["slack_active"]),
        }
        return json.dumps({"status": "loaded", "summary": summary})

    elif name == "run_audit_checks":
        issues, hours_issues = run_all()
        ctx = load_all()
        # Store for generate_html_report
        _audit_results["issues"] = issues
        _audit_results["hours_issues"] = hours_issues
        _audit_results["total_entries"] = len(ctx["ts"])

        n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
        n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
        n_info = sum(1 for i in issues if i["severity"] == "INFO")
        top = [
            {"check": i["check"], "label": i["label"], "user": i["user"],
             "date": i["date"], "brief": i["brief"]}
            for i in issues[:20]  # top 20 to keep the message size sane
        ]
        return json.dumps({
            "summary": {
                "total_entries": len(ctx["ts"]),
                "total_issues": len(issues),
                "critical": n_crit,
                "warning": n_warn,
                "info": n_info,
            },
            "top_issues": top,
        })

    elif name == "generate_html_report":
        if not _audit_results:
            return json.dumps({"error": "run_audit_checks must be called first"})
        path = generate(
            issues=_audit_results["issues"],
            hours_issues=_audit_results["hours_issues"],
            total_entries=_audit_results["total_entries"],
        )
        return json.dumps({"status": "written", "path": path})

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------
def main() -> None:
    model = os.environ.get("MODEL", "claude-opus-4-6")
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    print(f"[audit-agent] Starting with model={model}", flush=True)

    messages = [
        {
            "role": "user",
            "content": (
                "Run a full timesheet audit: "
                "1. Load all source data. "
                "2. Run all audit checks. "
                "3. Generate the HTML report. "
                "After the report is written, print a concise plain-text summary "
                "of the findings (total entries, critical/warning/info counts, "
                "and the top issues by severity)."
            ),
        }
    ]

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            tools=TOOLS,
            messages=messages,
        )

        # Collect any tool calls in this turn
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"[audit-agent] Calling tool: {block.name}", flush=True)
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Print Claude's final message
            for block in response.content:
                if hasattr(block, "text"):
                    print(block.text)
            break

        # Append tool results and continue the loop
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            # stop_reason was not end_turn but no tool calls — shouldn't happen
            print("[audit-agent] Unexpected stop with no tool calls. Exiting.", file=sys.stderr)
            sys.exit(1)

    print("[audit-agent] Done.", flush=True)


if __name__ == "__main__":
    main()
