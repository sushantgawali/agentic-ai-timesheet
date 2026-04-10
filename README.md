# Agentic AI Timesheet Auditor

An 8-agent revenue intelligence pipeline that audits timesheet exports, detects billing issues, checks contract compliance, and generates an actionable HTML report — before the invoice goes out.

---

## What it solves

- **Revenue leakage** — hours logged at wrong rates, Slack work with no timesheet entry, cap overages
- **Contract compliance** — billing on leave days, public holidays, to archived projects, by deactivated employees
- **SOW validation** — actual hours/cost vs contracted budget per project, role mismatches against team rosters
- **Data quality** — missing descriptions, invalid timestamps, overlapping entries, hours field errors
- **Slack signal detection** — classifies messages to surface unlogged work, scope changes, and escalations
- **Invoice readiness** — drafts line items with contract rates, flags lines needing human review before sending

---

## Agent pipeline

Eight focused sub-agents run sequentially. Each calls MCP tools, writes output to shared state on disk, and passes a plain-text summary to the next phase.

```
audit_agent_sdk.py  (orchestrator)
        │
        ├── Phase 1 ──────────────────────────────────────────────────┐
        │   ├── Normalization Agent    → build_work_units             │
        │   ├── Contract Agent         → build_contract_model         │  parallel-ready
        │   └── Context Mining Agent   → extract_slack_signals        │
        │                                                              ┘
        │              writes ──────────────────────────────────────────────────────────┐
        │                     work_units.json                                           │
        │                     contract_model.json                                       │
        │                     slack_signals.json                                        │
        │                                                              ┌────────────────┘
        ├── Phase 2                                                    │ output/agent_state/
        │   └── Reconciliation Agent   → reconcile_work  ─────────────┤ (flat-file JSON store)
        │         reads:  work_units + contract_model                  │ full findings saved here;
        │         writes: reconciled.json                              │ tool responses return only
        │                                                              │ summaries to avoid context
        ├── Phase 3 ──────────────────────────────────────────────────┤ overflow
        │   ├── Revenue Leakage Agent  → detect_revenue_leakage       │
        │   │     reads:  reconciled + slack_signals + contract_model  │
        │   │     writes: leakage_findings.json                        │
        │   └── Compliance Agent       → run_compliance_checks         │
        │         reads:  reconciled + contract_model                  │
        │         writes: compliance_findings.json                     │
        │                                                              │
        ├── Phase 4                                                    │
        │   └── Invoice Drafting Agent → build_invoice_draft           │
        │         reads:  reconciled + contract_model                  │
        │         writes: invoice_draft.json                           │
        │                                                              │
        └── Phase 5                                                    │
            └── Review & Alert Agent  → generate_full_report ─────────┘
                  reads:  all state files
                  writes: output/audit_*.html
```

Each agent talks to `audit/mcp_server.py` over stdio (MCP protocol). State files persist across runs — if the pipeline crashes mid-way, earlier phases don't need to re-run.

---

## Report

The generated HTML report (`output/audit_*.html`) contains:

- **Invoice status badge** — ACTION REQUIRED / NEEDS REVIEW / READY
- **Key takeaways** — 5–7 AI-generated, specific, actionable insights
- **Revenue leakage** — grouped by type, each with USD impact estimate
- **Compliance blockers** — CRITICAL and WARNING findings with policy clause references
- **Unlogged Slack work** — messages that signal billable activity with no timesheet
- **Invoice draft** — line items by project with contract rates and flag review
- **Project budget vs actuals** — hours and cost against SOW limits
- **Audit checks** — 15 legacy checks (invalid timestamps, overlaps, rate mismatches, etc.)
- **Data quality** — per-flag accordion tables with source file evidence

All sections are collapsible accordions with fixed-height scrollable tables and source file chips per finding.

---

## Quick start

```bash
pip install claude-agent-sdk mcp anyio
export ANTHROPIC_API_KEY=sk-...
export DATA_DIR=data/v5
python audit_agent_sdk.py
# Report written to output/audit_v5_haiku_YYYY-MM-DD.html
```

Optional env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `data` | Path to the data folder |
| `OUT_DIR` | `output` | Where the HTML report is written |
| `MODEL` | `claude-haiku-4-5-20251001` | Claude model to use |

---

## Data sources

Drop any combination of CSVs into `DATA_DIR`. The loader scans column headers and infers each file's role automatically — no fixed filenames required.

| Role | Key columns |
|------|-------------|
| Timesheets | `user`, `date`, `hours`, `begin`, `end` |
| Employees | `user`, `hourly_rate` / `rate`, `status` |
| Assignments | `user`, `project` |
| Leave | `user`, `date`, `leave_type` |
| Projects | `project`, `status`, `budget` |
| Slack | `user`, `date`, `text` / `channel` |
| Holidays | `date`, `holiday` / `name` |

SOW documents go in `DATA_DIR/documents/sow/` (`.docx`).
HR policy guidelines go in `DATA_DIR/documents/guidelines/` (`.pdf` or `.docx`).

---

## Project structure

```
.
├── audit_agent_sdk.py          # Orchestrator — runs 8 agents sequentially
│
├── audit/
│   ├── mcp_server.py           # stdio MCP server — 13 tools (phases 1–5)
│   ├── loader.py               # File-agnostic CSV + DOCX loader
│   ├── checks.py               # 15 legacy audit checks
│   ├── report.py               # HTML report generator
│   └── agents/
│       ├── normalization.py    # Build WorkUnit records from timesheets
│       ├── contract.py         # Parse SOW + guidelines → ContractModel
│       ├── slack_mining.py     # Classify Slack messages → signals
│       ├── reconciliation.py   # Mark billable/non-billable, detect dupes
│       ├── leakage.py          # Detect revenue leakage, estimate USD impact
│       ├── compliance.py       # Run 6 compliance checks (CRITICAL/WARNING)
│       └── invoice.py          # Draft invoice line items with contract rates
│
├── data/
│   ├── v2/                     # Baseline dataset (8 CSVs)
│   ├── v3/                     # Extended dataset
│   └── v5/                     # Full dataset
│       ├── *.csv               # 9 CSV files
│       └── documents/
│           ├── sow/            # 17 SOW DOCX files
│           └── guidelines/     # HR policy PDFs + DOCXs
│
├── output/                     # Generated reports (git-ignored)
│   └── agent_state/            # Inter-agent state (JSON, git-ignored)
│
├── docs/                       # Supplementary documentation
├── generate_index.py           # GitHub Pages index builder
└── requirements.txt
```
