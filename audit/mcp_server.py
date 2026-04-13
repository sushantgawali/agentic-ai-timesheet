#!/usr/bin/env python3
"""
Subprocess MCP server — exposes audit tools over stdio.

Spawned by audit_agent_sdk.py via ClaudeAgentOptions mcp_servers config.
Runs for the lifetime of the Claude Code CLI session, maintaining
shared state between tool calls via an on-disk state directory so that
multiple sub-agent processes can handshake through the file system.

Tool groups
-----------
  Legacy (single-agent flow, still supported):
    discover_data_files, read_guidelines_documents, read_sow_documents,
    load_timesheet_data, run_audit_checks, generate_html_report

  Phase 1 — independent, can run in parallel:
    build_work_units       → Normalization & Linking Agent
    build_contract_model   → Contract Interpreter Agent
    extract_slack_signals  → Context Mining Agent

  Phase 2:
    reconcile_work         → Work Reconciliation Agent

  Phase 3 — independent, can run in parallel:
    detect_revenue_leakage → Revenue Leakage Agent
    run_compliance_checks  → Compliance & Risk Agent

  Phase 4:
    build_invoice_draft    → Invoice Drafting Agent

  Phase 5:
    generate_full_report   → Review & Alert Agent
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from audit.loader import load_all, discover_csv_files, load_sow_documents, load_guidelines_documents, DATA_VERSION
from audit.report_builder import generate

app = Server("audit-tools")

# ---------------------------------------------------------------------------
# In-process state (for the legacy single-agent flow)
# ---------------------------------------------------------------------------
_results: dict = {}

# ---------------------------------------------------------------------------
# On-disk state directory (shared across sub-agent processes)
# ---------------------------------------------------------------------------

_STATE_DIR = os.path.join(os.environ.get("OUT_DIR", "output"), "agent_state")


def _state_path(key: str) -> str:
    os.makedirs(_STATE_DIR, exist_ok=True)
    return os.path.join(_STATE_DIR, f"{key}.json")


def _save_state(key: str, data: dict) -> None:
    with open(_state_path(key), "w") as f:
        json.dump(data, f)


def _load_state(key: str) -> dict | None:
    path = _state_path(key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)



def _require_state(key: str, caller: str) -> dict:
    data = _load_state(key)
    if data is None:
        raise RuntimeError(
            f"{caller} requires '{key}' state — call the appropriate upstream tool first."
        )
    return data


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ---------------------------------------------------------------- #
        # Legacy tools                                                      #
        # ---------------------------------------------------------------- #
        Tool(
            name="read_sow_documents",
            description=(
                "Parse all Statement of Work (SOW) DOCX files and return structured data: "
                "project name, client, SOW reference, effective/end dates, contracted monthly "
                "value, and team composition (name, role, allocation %, rate, monthly hours). "
                "Use this to cross-reference who should be billing to each project and at what rate."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="read_guidelines_documents",
            description=(
                "Parse all HR policy and guideline documents (PDF/DOCX) and return their text. "
                "Use this to understand company policies on leave, holidays, timesheets, and "
                "billing rules — cross-reference with audit findings to identify policy violations."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="discover_data_files",
            description=(
                "Scan the data directory for all CSV files, read column headers, and infer "
                "each file's semantic role (timesheets, employees, assignments, leave, projects, "
                "slack, git, holidays, calendar_leave, emails, calendar). Call this first."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="load_timesheet_data",
            description=(
                "Load all CSV source files from the data directory and return a loading summary."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="run_audit_checks",
            description=(
                "Run all 15 audit checks against the loaded data. "
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
                "Pass key_takeaways_json as a JSON-encoded array of 3-5 concise insight strings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key_takeaways_json": {
                        "type": "string",
                        "description": "JSON-encoded array of insight strings.",
                    }
                },
                "required": [],
            },
        ),

        # ---------------------------------------------------------------- #
        # Phase 1 — Normalization, Contract, Slack (run in parallel)        #
        # ---------------------------------------------------------------- #
        Tool(
            name="build_work_units",
            description=(
                "Normalization & Linking Agent — transform all timesheet rows into enriched "
                "WorkUnit records. Each unit includes: user, date, project, activity, hours "
                "(declared & calculated), rates, assignment status, leave status, employee "
                "status, project status, weekend/holiday flags, and data quality flags "
                "(missing_activity, missing_description, hours_mismatch, invalid_timestamp, etc.). "
                "Saves results to agent state. Returns summary + full work_units list."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="build_contract_model",
            description=(
                "Contract Interpreter Agent — extract structured billing rules from all SOW "
                "documents and HR guideline documents. Returns a ContractModel with: "
                "per-project billing type, monthly cap hours, team roster (name/role/rate/hours), "
                "and global rules (overtime approval requirement, leave types, billing exclusions). "
                "Saves results to agent state."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="extract_slack_signals",
            description=(
                "Context Mining Agent — classify Slack messages into four signal types: "
                "work_activity (evidence of work done), approval (go-ahead for overtime/scope), "
                "scope_change (informal extra-work requests), escalation (urgent production issues). "
                "Cross-references signals against timesheet days to find unlogged work. "
                "Saves results to agent state."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ---------------------------------------------------------------- #
        # Phase 2 — Reconciliation                                          #
        # ---------------------------------------------------------------- #
        Tool(
            name="reconcile_work",
            description=(
                "Work Reconciliation Agent — align work units with project assignments and "
                "the contract model. Marks each unit billable/non-billable with reasons, "
                "detects duplicate timesheet entries, flags role mismatches against contract "
                "team, and computes per-project hour totals. "
                "Requires build_work_units and build_contract_model to have run first."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ---------------------------------------------------------------- #
        # Phase 3 — Leakage + Compliance (run in parallel)                  #
        # ---------------------------------------------------------------- #
        Tool(
            name="detect_revenue_leakage",
            description=(
                "Revenue Leakage Agent — identify missed or incorrect billing across five types: "
                "(1) rate_mismatch: billed at wrong hourly rate — compared against SOW contract rate first, HR canonical rate as fallback, "
                "(2) unlogged_work: Slack signals of work done with no timesheet entry, "
                "(3) cap_overage: hours logged beyond per-user monthly contract cap, "
                "(4) scope_creep_untagged: informal scope-change Slack messages with no change order, "
                "(5) archived_project_hours: billing hours recoverable by re-tagging. "
                "Returns findings with estimated USD impact. "
                "Requires reconcile_work and extract_slack_signals."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="run_compliance_checks",
            description=(
                "Compliance & Risk Agent — check contract adherence across six risk categories: "
                "(1) unauthorized_overtime: >8h/day without written approval, "
                "(2) leave_day_billing: timesheet on approved leave day, "
                "(3) public_holiday_billing: billing on public holiday without approval, "
                "(4) deactivated_employee_billing: inactive user has entries, "
                "(5) archived_project_billing: billing to closed project, "
                "(6) unassigned_project_billing: resource not assigned but billing. "
                "Requires reconcile_work and build_contract_model."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ---------------------------------------------------------------- #
        # Phase 4 — Invoice Drafting                                        #
        # ---------------------------------------------------------------- #
        Tool(
            name="build_invoice_draft",
            description=(
                "Invoice Drafting Agent — aggregate billable work units into invoice line items "
                "by (project, user). Applies contract rates where available, falls back to "
                "timesheet rates. Returns line items, project subtotals, grand total, and "
                "warnings about rate fallbacks or role mismatches. "
                "Requires reconcile_work and build_contract_model."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ---------------------------------------------------------------- #
        # Phase 5 — Review & Alert                                          #
        # ---------------------------------------------------------------- #
        Tool(
            name="generate_full_report",
            description=(
                "Review & Alert Agent — generate the final HTML report combining legacy audit "
                "check findings with the new revenue intelligence findings (leakage, compliance, "
                "invoice draft, Slack signals). Also accepts key_takeaways_json for a top-level "
                "insights panel. Requires all upstream agents to have run first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key_takeaways_json": {
                        "type": "string",
                        "description": "JSON-encoded array of 3-7 top insight strings.",
                    },
                    "executive_insights_json": {
                        "type": "string",
                        "description": (
                            "JSON-encoded executive insights object with keys: "
                            "top_revenue_risks, top_compliance_blockers, quick_wins, "
                            "critical_human_review. Copy verbatim from your <insights_json> block."
                        ),
                    },
                },
                "required": [],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    def ok(data: dict) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data))]

    def err(msg: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"error": msg}))]

    try:
        # ---------------------------------------------------------------- #
        # Legacy tools                                                      #
        # ---------------------------------------------------------------- #
        if name == "read_guidelines_documents":
            docs = load_guidelines_documents()
            return ok({
                "guidelines_count": len(docs),
                "guidelines": [
                    {"filename": d["filename"], "type": d["type"], "text": d["text"]}
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
                    "note": "project_name in SOW may differ from project name used in timesheets",
                })

            return ok({
                "sow_count":       len(sow_docs),
                "sow_documents":   enriched,
                "project_actuals": {
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
                    "Use customer/scope context to match them."
                ),
            })

        elif name == "discover_data_files":
            files = discover_csv_files()
            return ok({
                "data_dir":    os.environ.get("DATA_DIR", "data"),
                "files_found": len(files),
                "files": [
                    {"filename": f["filename"], "columns": f["columns"], "role": f["role"]}
                    for f in files
                ],
                "roles_detected": {f["role"]: f["filename"] for f in files if f["role"]},
                "unrecognised":   [f["filename"] for f in files if not f["role"]],
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
            from audit.checks import run_all
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
                {"check": i["check"], "label": i["label"], "user": i["user"],
                 "date": i["date"], "brief": i["brief"]}
                for i in issues[:20]
            ]
            return ok({
                "summary": {
                    "total_entries": len(ctx["ts"]),
                    "total_issues":  len(issues),
                    "critical": n_crit, "warning": n_warn, "info": n_info,
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

        # ---------------------------------------------------------------- #
        # Phase 1 — Normalization                                           #
        # ---------------------------------------------------------------- #
        elif name == "build_work_units":
            from audit.tools.normalization import build_work_units
            result = build_work_units()
            _save_state("work_units", result)
            return ok({
                "status":          "saved",
                "total_entries":   result["total_entries"],
                "users":           result["users"],
                "projects":        result["projects"],
                "quality_summary": result["quality_summary"],
                "data_quality_issue_count": len(result["data_quality_issues"]),
                "sample_issues":   result["data_quality_issues"][:10],
                "hint": (
                    "WorkUnits saved to agent state. Each unit carries: is_assigned, "
                    "is_on_leave, is_deactivated, is_archived_project, data_quality_flags. "
                    "Call reconcile_work next (after build_contract_model)."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 1 — Contract Interpreter                                    #
        # ---------------------------------------------------------------- #
        elif name == "build_contract_model":
            from audit.tools.contract import build_contract_model
            result = build_contract_model()
            _save_state("contract_model", result)

            proj_summaries = {
                pname: {
                    "monthly_cap_hours": pdata.get("monthly_cap_hours"),
                    "billing_type":      pdata.get("billing_type"),
                    "team_size":         len(pdata.get("team", [])),
                    "requires_ot_approval": pdata.get("requires_overtime_approval"),
                }
                for pname, pdata in result["projects"].items()
            }
            return ok({
                "status":            "saved",
                "sow_count":         result["sow_count"],
                "guideline_count":   result["guideline_count"],
                "projects":          proj_summaries,
                "global_rules":      result["global_rules"],
                "hint": (
                    "ContractModel saved. 'team_map' in each project enables user-to-rate lookup. "
                    "Call reconcile_work next (after build_work_units)."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 1 — Context Mining (Slack)                                  #
        # ---------------------------------------------------------------- #
        elif name == "extract_slack_signals":
            from audit.tools.slack_mining import run_slack_mining
            result = run_slack_mining()
            _save_state("slack_signals", result)
            return ok({
                "status":              "saved",
                "total_signals":       result["total_signals"],
                "signal_type_counts":  result["signal_type_counts"],
                "unlogged_work_count": result["unlogged_work_count"],
                "unlogged_by_user":    result["unlogged_by_user"],
                "sample_unlogged":     result["work_without_timesheet"][:10],
                "sample_scope_changes": [
                    s for s in result["signals"]
                    if "scope_change" in s["signal_types"]
                ][:5],
                "hint": (
                    "Slack signals saved. unlogged_work_count = Slack work_activity messages "
                    "with no corresponding timesheet entry — potential revenue leakage. "
                    "scope_change signals = informal extra-work requests needing change orders."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 2 — Reconciliation                                          #
        # ---------------------------------------------------------------- #
        elif name == "reconcile_work":
            work_units_data  = _require_state("work_units",     "reconcile_work")
            contract_model   = _require_state("contract_model", "reconcile_work")
            from audit.tools.reconciliation import reconcile_work as _reconcile
            result = _reconcile(work_units_data["work_units"], contract_model)
            _save_state("reconciled", result)
            return ok({
                "status":                  "saved",
                "billable_count":          result["billable_count"],
                "non_billable_count":      result["non_billable_count"],
                "total_billable_hours":    result["total_billable_hours"],
                "total_non_billable_hours": result["total_non_billable_hours"],
                "duplicate_count":         len(result["duplicates"]),
                "role_mismatch_count":     len(result["role_mismatches"]),
                "project_totals":          result["project_totals"],
                "sample_role_mismatches":  result["role_mismatches"][:5],
                "hint": (
                    "Reconciled work saved. non_billable_units have non_billable_reasons. "
                    "Now run detect_revenue_leakage and run_compliance_checks in parallel."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 3 — Revenue Leakage                                         #
        # ---------------------------------------------------------------- #
        elif name == "detect_revenue_leakage":
            reconciled     = _require_state("reconciled",     "detect_revenue_leakage")
            slack_signals  = _require_state("slack_signals",  "detect_revenue_leakage")
            contract_model = _require_state("contract_model", "detect_revenue_leakage")
            ctx            = load_all()
            from audit.tools.leakage import detect_revenue_leakage as _leakage
            result = _leakage(
                reconciled=reconciled,
                slack_signals=slack_signals,
                contract_model=contract_model,
                proj_actual_hours=ctx.get("proj_actual_hours", {}),
                proj_budget_hours=ctx.get("proj_budget_hours", {}),
            )
            _save_state("leakage_findings", result)
            return ok({
                "status":                 "saved",
                "total_findings":         result["total_findings"],
                "total_estimated_impact": result["total_estimated_impact"],
                "finding_type_counts":    result["finding_type_counts"],
                "critical_count":         result["critical_count"],
                "warning_count":          result["warning_count"],
                "sample_findings":        result["findings"][:15],
                "note": (
                    f"Full {result['total_findings']} findings saved to agent state. "
                    "Sample of first 15 shown above."
                ),
                "hint": (
                    "Leakage findings saved. total_estimated_impact = total USD revenue at risk. "
                    "critical_count items require immediate attention before invoicing."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 3 — Compliance & Risk                                       #
        # ---------------------------------------------------------------- #
        elif name == "run_compliance_checks":
            reconciled     = _require_state("reconciled",     "run_compliance_checks")
            contract_model = _require_state("contract_model", "run_compliance_checks")
            from audit.tools.compliance import run_compliance_checks as _compliance
            result = _compliance(reconciled=reconciled, contract_model=contract_model)
            _save_state("compliance_findings", result)
            return ok({
                "status":              "saved",
                "total_findings":      result["total_findings"],
                "finding_type_counts": result["finding_type_counts"],
                "critical_count":      result["critical_count"],
                "warning_count":       result["warning_count"],
                "sample_findings":     result["findings"][:15],
                "note": (
                    f"Full {result['total_findings']} findings saved to agent state. "
                    "Sample of first 15 shown above."
                ),
                "hint": (
                    "Compliance findings saved. critical items must be resolved before invoicing. "
                    "warning items should be reviewed and documented."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 4 — Invoice Drafting                                        #
        # ---------------------------------------------------------------- #
        elif name == "build_invoice_draft":
            reconciled     = _require_state("reconciled",     "build_invoice_draft")
            contract_model = _require_state("contract_model", "build_invoice_draft")
            from audit.tools.invoice import build_invoice_draft as _invoice
            result = _invoice(reconciled=reconciled, contract_model=contract_model)
            _save_state("invoice_draft", result)
            flagged_lines = [l for l in result["invoice_lines"] if l.get("flags")]
            return ok({
                "status":               "saved",
                "grand_total":          result["grand_total"],
                "billable_hours_total": result["billable_hours_total"],
                "line_item_count":      result["line_item_count"],
                "project_subtotals":    result["project_subtotals"],
                "flagged_lines":        flagged_lines[:20],
                "flagged_line_count":   len(flagged_lines),
                "warnings":             result["warnings"][:20],
                "note": (
                    f"Full {result['line_item_count']} invoice lines saved to agent state. "
                    "Flagged lines (rate_fallback / role_mismatch) shown above."
                ),
                "hint": (
                    "Invoice draft saved. Lines with 'rate_fallback' flag use timesheet rates "
                    "instead of contract rates — verify before sending. "
                    "Lines with 'role_mismatch' flag should be reviewed against the SOW."
                ),
            })

        # ---------------------------------------------------------------- #
        # Phase 5 — Generate Full Report                                    #
        # ---------------------------------------------------------------- #
        elif name == "generate_full_report":
            ctx = load_all()

            raw = arguments.get("key_takeaways_json", "[]") or "[]"
            try:
                takeaways = json.loads(raw)
                if not isinstance(takeaways, list):
                    takeaways = [str(takeaways)]
            except Exception:
                takeaways = [raw] if raw != "[]" else []

            raw_insights = arguments.get("executive_insights_json", "") or ""
            executive_insights: dict = {}
            if raw_insights:
                try:
                    executive_insights = json.loads(raw_insights)
                    if not isinstance(executive_insights, dict):
                        executive_insights = {}
                except Exception:
                    executive_insights = {}

            # Load all intelligence-pipeline state
            leakage          = _load_state("leakage_findings")
            compliance       = _load_state("compliance_findings")
            invoice          = _load_state("invoice_draft")
            slack_state      = _load_state("slack_signals")
            work_units_state = _load_state("work_units")

            path = generate(
                issues=[],
                hours_issues=[],
                total_entries=len(ctx["ts"]),
                key_takeaways=takeaways,
                data_version=DATA_VERSION,
                model=os.environ.get("MODEL", "claude-haiku-4-5-20251001"),
                proj_budget_hours=ctx.get("proj_budget_hours", {}),
                proj_budget_cost=ctx.get("proj_budget_cost",  {}),
                proj_actual_hours=ctx.get("proj_actual_hours", {}),
                proj_actual_cost=ctx.get("proj_actual_cost",  {}),
                leakage_findings=leakage,
                compliance_findings=compliance,
                invoice_draft=invoice,
                slack_signals=slack_state,
                work_units_data=work_units_state,
                reconciled_data=_load_state("reconciled"),
                executive_insights=executive_insights or None,
            )
            return ok({
                "status":                 "written",
                "path":                   path,
                "leakage_findings":       leakage.get("total_findings", 0) if leakage else 0,
                "compliance_findings":    compliance.get("total_findings", 0) if compliance else 0,
                "invoice_grand_total":    invoice.get("grand_total", 0) if invoice else 0,
                "slack_unlogged_signals": slack_state.get("unlogged_work_count", 0) if slack_state else 0,
            })

        else:
            return err(f"Unknown tool: {name}")

    except Exception as exc:
        import traceback
        return err(f"{exc}\n{traceback.format_exc()}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)
