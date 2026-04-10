#!/usr/bin/env python3
"""
Multi-agent Revenue Intelligence Orchestrator — Agent SDK entry point.

Runs eight focused sub-agents in a directed pipeline that prioritises:
  • Revenue leakage detection
  • Contract compliance checks
  • Missing / inconsistent data flags
  • Slack-based work detection

Pipeline (numbers indicate parallelism):
  1a. Normalization Agent   ─┐
  1b. Contract Agent        ─┼─ (parallel)
  1c. Context Mining Agent  ─┘
  2.  Reconciliation Agent
  3a. Revenue Leakage Agent ─┐ (parallel)
  3b. Compliance Agent      ─┘
  4.  Invoice Drafting Agent
  5.  Review & Alert Agent

Each sub-agent calls focused MCP tools, reasons over the results, and
writes structured output to the shared agent_state/ directory so the next
phase can consume it.

Requires:
    pip install claude-agent-sdk mcp anyio
    npm install -g @anthropic-ai/claude-code

Required env var: ANTHROPIC_API_KEY
Optional env vars:
    DATA_DIR  (default: data)
    OUT_DIR   (default: output)
    MODEL     (default: claude-haiku-4-5-20251001)
"""
import os
import sys
from pathlib import Path

import anyio

from claude_agent_sdk import (
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    query,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL        = os.environ.get("MODEL",        "claude-haiku-4-5-20251001")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6")
DATA_DIR     = os.environ.get("DATA_DIR", "data")
OUT_DIR      = os.environ.get("OUT_DIR",  "output")
SERVER_SCRIPT = str(Path(__file__).parent / "audit" / "mcp_server.py")


def _mcp_options(max_turns: int = 6, model: str = MODEL) -> ClaudeAgentOptions:
    """Return ClaudeAgentOptions wired to the shared MCP server."""
    return ClaudeAgentOptions(
        model=model,
        mcp_servers={
            "audit": {
                "type":    "stdio",
                "command": "python3",
                "args":    [SERVER_SCRIPT],
                "env": {
                    "DATA_DIR":   DATA_DIR,
                    "OUT_DIR":    OUT_DIR,
                    "PYTHONPATH": str(Path(__file__).parent),
                },
            }
        },
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )


async def _run_agent(label: str, prompt: str, max_turns: int = 6, model: str = MODEL) -> str:
    """
    Run a single sub-agent, stream its output to stdout, and return
    the concatenated text from all AssistantMessage blocks.
    """
    print(f"\n{'='*60}", flush=True)
    print(f"[{label}] Starting...", flush=True)
    print(f"{'='*60}", flush=True)

    text_parts: list[str] = []
    options = _mcp_options(max_turns=max_turns, model=model)

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)
                    text_parts.append(block.text)
        elif isinstance(message, ResultMessage):
            cost_usd = getattr(message, "cost_usd", None)
            cost = f" | cost: ${cost_usd:.4f}" if cost_usd else ""
            print(f"\n[{label}] Done{cost}.", flush=True)

    return "".join(text_parts)


# ---------------------------------------------------------------------------
# Agent prompts
# ---------------------------------------------------------------------------

_NORMALIZATION_PROMPT = """
You are the Normalization & Linking Agent in a multi-agent revenue intelligence pipeline.

Your job: Transform all raw timesheet data into enriched WorkUnit records so that downstream
agents can reason about billability, compliance, and revenue leakage without touching raw CSVs.

Steps:
1. Call discover_data_files to understand what data is available.
2. Call build_work_units to normalize all timesheet rows into WorkUnits.
3. Review the quality_summary in the response:
   - Identify which quality flags are most prevalent (missing_activity, hours_mismatch, etc.)
   - Note which users or projects have the most data quality issues.
4. Print a concise summary covering:
   - Total entries processed and distinct users/projects.
   - Top 3 data quality issues by count.
   - Any users with multiple quality flags (high-risk for billing disputes).

Do NOT call any other tools. Your output is saved automatically for downstream agents.
""".strip()

_CONTRACT_PROMPT = """
You are the Contract Interpreter Agent in a multi-agent revenue intelligence pipeline.

Your job: Extract structured billing rules from all SOW and guideline documents so that
downstream agents can validate timesheets against contract terms.

Steps:
1. Call build_contract_model to parse all SOW and guideline documents.
2. Review the returned ContractModel:
   - List each project with its monthly_cap_hours and team roster.
   - Note the global_rules (overtime approval, billing exclusions, etc.).
   - Flag any projects where monthly_cap_hours is None (no cap defined — risk of over-billing).
   - Flag any ambiguous or missing clauses (e.g., no end_date, no rate for a team member).
3. Print a concise summary covering:
   - How many SOWs and guideline docs were parsed.
   - Per-project: billing type, monthly cap hours, team size.
   - Global rules that will affect compliance checks.
   - Any missing or ambiguous contract data to watch for.

Do NOT call any other tools. Your output is saved automatically for downstream agents.
""".strip()

_SLACK_MINING_PROMPT = """
You are the Context Mining Agent (Slack) in a multi-agent revenue intelligence pipeline.

Your job: Classify Slack messages to find hidden work signals, approvals, and scope changes
that may represent billable activity not yet recorded in timesheets.

Steps:
1. Call extract_slack_signals to classify all Slack messages.
2. Review the returned signals:
   - work_without_timesheet: these are your primary revenue leakage signals.
   - scope_change signals: informal requests for extra work needing change orders.
   - approval signals: verbal go-aheads that may authorise overtime or scope.
   - escalation signals: urgent work that often generates unlogged hours.
3. Print a concise summary covering:
   - Total signals found per type.
   - Top users with unlogged work signals (by count).
   - Notable scope change or escalation messages worth highlighting.
   - Any channels with especially high signal density.

Do NOT call any other tools. Your output is saved automatically for downstream agents.
""".strip()

_RECONCILIATION_PROMPT = """
You are the Work Reconciliation Agent in a multi-agent revenue intelligence pipeline.

Your job: Align every WorkUnit with project assignments and the contract model to determine
what is billable, detect duplicates, and flag role mismatches before invoicing.

Prerequisites: build_work_units and build_contract_model must have run already.

Steps:
1. Call reconcile_work to align work units with assignments and contract rules.
2. Review the reconciliation results:
   - Compare billable_count vs non_billable_count — a high non-billable ratio is a red flag.
   - Check duplicate_count — duplicates inflate hours and must be removed before invoicing.
   - Check role_mismatches — users billing to projects they're not contracted for.
   - Review project_totals to identify projects with significant non-billable hours.
3. Print a concise summary covering:
   - Total billable vs non-billable hours (and why hours are non-billable).
   - Duplicate entries found (if any).
   - Role mismatches that could cause invoice disputes.
   - Projects with the highest non-billable hour ratio.

Do NOT call any other tools. Your output is saved automatically for downstream agents.
""".strip()

_LEAKAGE_PROMPT = """
You are the Revenue Leakage Agent in a multi-agent revenue intelligence pipeline.

Your job: Identify all forms of missed or incorrect billing so that revenue can be recovered
before the invoice is sent. Every finding should be concrete, actionable, and financially
quantified where possible.

Prerequisites: reconcile_work and extract_slack_signals must have run already.

Steps:
1. Call detect_revenue_leakage to find all leakage signals.
2. Analyse the findings by type:
   - rate_mismatch: Who is being under-billed or over-billed and by how much?
   - unlogged_work: Which Slack-evidenced work has no timesheet entry?
   - cap_overage: Which users have logged beyond their monthly contract cap?
   - scope_creep_untagged: Which informal scope expansions have no change order?
3. Print a concise summary covering:
   - Total estimated revenue at risk (USD).
   - Top 3 leakage signals by financial impact.
   - Any users who appear repeatedly across multiple leakage types.
   - Recommended actions before invoicing (e.g., "Chase timesheet from X for Y date").

Do NOT call any other tools. Your findings are saved automatically.
""".strip()

_COMPLIANCE_PROMPT = """
You are the Compliance & Risk Agent in a multi-agent revenue intelligence pipeline.

Your job: Identify every contract and policy violation that could cause invoice rejection,
client disputes, or legal/audit risk. Every finding must be resolved before the invoice is sent.

Prerequisites: reconcile_work and build_contract_model must have run already.

Steps:
1. Call run_compliance_checks to evaluate all compliance rules.
2. Analyse findings by severity:
   - CRITICAL: must be fixed before invoicing (leave-day billing, deactivated employee, archived project).
   - WARNING: should be reviewed and documented (overtime, public holiday, unassigned project).
3. Print a concise summary covering:
   - CRITICAL blocking issues that prevent invoice from being sent.
   - WARNING items that need documentation or approval records.
   - Which contract clauses are being violated (e.g., "overtime_requires_approval").
   - Recommended resolution steps for each finding type.

Do NOT call any other tools. Your findings are saved automatically.
""".strip()

_INVOICE_PROMPT = """
You are the Invoice Drafting Agent in a multi-agent revenue intelligence pipeline.

Your job: Produce a clean, accurate invoice draft from the billable work units, applying
contract rates and flagging any line items that need human review before sending.

Prerequisites: reconcile_work and build_contract_model must have run already.

Steps:
1. Call build_invoice_draft to generate invoice line items.
2. Review the draft:
   - Grand total and per-project subtotals.
   - Lines with rate_fallback flag: contract rate unavailable — verify rate is correct.
   - Lines with role_mismatch flag: user not in contract team — needs approval before billing.
   - Any warnings about missing rate data.
3. Print a concise summary covering:
   - Invoice grand total and billable hours total.
   - Project-level breakdown of subtotals.
   - Lines requiring human review before sending.
   - Any adjustments recommended based on leakage or compliance findings.

Do NOT call any other tools. Your draft is saved automatically.
""".strip()


def _review_prompt(
    norm_summary:       str,
    contract_summary:   str,
    slack_summary:      str,
    recon_summary:      str,
    leakage_summary:    str,
    compliance_summary: str,
    invoice_summary:    str,
) -> str:
    return f"""
You are the Review & Alert Agent — the final agent in the revenue intelligence pipeline.

Your job: Synthesise all upstream agent outputs into a final actionable report that a billing
manager can act on immediately. Generate the HTML report with key takeaways, then print a
plain-text executive summary.

UPSTREAM AGENT OUTPUTS
======================
[Normalization Agent]
{norm_summary}

[Contract Agent]
{contract_summary}

[Context Mining Agent]
{slack_summary}

[Reconciliation Agent]
{recon_summary}

[Revenue Leakage Agent]
{leakage_summary}

[Compliance Agent]
{compliance_summary}

[Invoice Drafting Agent]
{invoice_summary}

STEPS
=====
1. Synthesise all upstream findings into 5–7 key takeaways.
   Each takeaway must be specific, concise, and actionable. Examples:
     - "3 users logged hours on public holidays — requires client approval or reversal."
     - "rishabh.a billed Entain-CRM but is NOT in the SOW team — dispute risk."
     - "Estimated $X revenue at risk from rate mismatches and unlogged Slack work."
     - "Invoice draft total: $Y — 2 lines flagged for role mismatch review."

2. Call generate_full_report with key_takeaways_json set to a JSON array of your 5–7 takeaways.

3. Print a plain-text executive summary covering:
   - Invoice readiness (READY / BLOCKED / NEEDS REVIEW) with reason.
   - Top 3 revenue risks to address before sending the invoice.
   - Top 3 compliance blockers.
   - Any quick wins (e.g., timesheets that can be easily recovered or corrected).
""".strip()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"[orchestrator] Starting Revenue Intelligence Pipeline", flush=True)
    print(f"[orchestrator] Agents: {MODEL}  |  Review: {REVIEW_MODEL}  |  Data: {DATA_DIR}  |  Output: {OUT_DIR}", flush=True)

    # Phase 1a — Normalization
    print("\n[Phase 1/3] Normalization Agent", flush=True)
    norm_summary = await _run_agent("Normalization Agent", _NORMALIZATION_PROMPT)

    # Phase 1b — Contract Interpreter
    print("\n[Phase 2/3] Contract Agent", flush=True)
    contract_summary = await _run_agent("Contract Agent", _CONTRACT_PROMPT)

    # Phase 1c — Context Mining (Slack)
    print("\n[Phase 3/3] Context Mining Agent", flush=True)
    slack_summary = await _run_agent("Context Mining Agent", _SLACK_MINING_PROMPT)

    # Phase 2 — Reconciliation
    print("\n[Phase 4] Reconciliation Agent", flush=True)
    recon_summary = await _run_agent("Reconciliation Agent", _RECONCILIATION_PROMPT)

    # Phase 3a — Revenue Leakage
    print("\n[Phase 5] Revenue Leakage Agent", flush=True)
    leakage_summary = await _run_agent("Revenue Leakage Agent", _LEAKAGE_PROMPT)

    # Phase 3b — Compliance
    print("\n[Phase 6] Compliance Agent", flush=True)
    compliance_summary = await _run_agent("Compliance Agent", _COMPLIANCE_PROMPT)

    # Phase 4 — Invoice Drafting
    print("\n[Phase 7] Invoice Drafting Agent", flush=True)
    invoice_summary = await _run_agent("Invoice Drafting Agent", _INVOICE_PROMPT)

    # Phase 5 — Review & Alert
    print("\n[Phase 8] Review & Alert Agent", flush=True)
    review_prompt = _review_prompt(
        norm_summary, contract_summary, slack_summary,
        recon_summary, leakage_summary, compliance_summary, invoice_summary,
    )
    review_summary = await _run_agent("Review & Alert Agent", review_prompt, max_turns=10, model=REVIEW_MODEL)

    # Guaranteed report generation — write directly from state files so the
    # report always lands in OUT_DIR regardless of what the Review Agent did.
    _generate_report_from_state(review_summary)

    print("\n[orchestrator] Pipeline complete.", flush=True)


def _generate_report_from_state(review_summary: str) -> None:
    """
    Load all agent state files and call report.generate() directly.
    This guarantees the HTML report is written to OUT_DIR even if the
    Review & Alert Agent wrote its output elsewhere or skipped the tool call.
    """
    import glob
    import json
    import re
    from pathlib import Path as _Path

    # Check if report already exists (agent called the tool correctly)
    existing = glob.glob(str(_Path(OUT_DIR) / "audit_*.html"))
    if existing:
        print(f"[orchestrator] Report already at {existing[0]}", flush=True)
        return

    print("[orchestrator] Report not found in OUT_DIR — generating directly from state files...", flush=True)

    state_dir = _Path(OUT_DIR) / "agent_state"

    def _load(key: str) -> dict:
        p = state_dir / f"{key}.json"
        if p.exists():
            with open(p) as f:
                return json.load(f)
        return {}

    leakage    = _load("leakage_findings")
    compliance = _load("compliance_findings")
    invoice    = _load("invoice_draft")
    slack      = _load("slack_signals")
    work_units = _load("work_units")
    reconciled = _load("reconciled")
    contract   = _load("contract_model")

    # Extract key takeaways from the review agent's text output
    takeaways: list = []
    json_match = re.search(r'\[.*?\]', review_summary, re.DOTALL)
    if json_match:
        try:
            takeaways = json.loads(json_match.group())
        except Exception:
            pass
    if not takeaways:
        # Fall back to numbered lines from the summary text
        for line in review_summary.splitlines():
            line = line.strip().lstrip("0123456789.-) ")
            if len(line) > 20:
                takeaways.append(line)
            if len(takeaways) >= 7:
                break

    from audit.loader import load_all
    from audit.checks import run_all
    from audit.report import generate

    ctx = load_all()
    issues, hours_issues = run_all(ctx)

    data_version = _Path(DATA_DIR).name
    out_path = generate(
        issues=issues,
        hours_issues=hours_issues,
        total_entries=work_units.get("total_entries", ctx.get("total_entries", 0)),
        key_takeaways=takeaways,
        data_version=data_version,
        model=REVIEW_MODEL,
        proj_budget_hours=ctx.get("proj_budget_hours", {}),
        proj_budget_cost=ctx.get("proj_budget_cost", {}),
        proj_actual_hours=ctx.get("proj_actual_hours", {}),
        proj_actual_cost=ctx.get("proj_actual_cost", {}),
        leakage_findings=leakage   or None,
        compliance_findings=compliance or None,
        invoice_draft=invoice  or None,
        slack_signals=slack    or None,
        work_units_data=work_units or None,
    )
    print(f"[orchestrator] Report written to {out_path}", flush=True)


if __name__ == "__main__":
    try:
        anyio.run(main)
    except Exception as e:
        print(f"[orchestrator] Fatal: {e}", file=sys.stderr)
        sys.exit(1)
