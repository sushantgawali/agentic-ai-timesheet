# Agentic AI Timesheet Auditor

A 9-agent revenue intelligence pipeline that audits timesheet exports, detects billing issues, checks contract compliance, and generates an actionable HTML report — before the invoice goes out.

Live reports: **[sushantgawali.github.io/agentic-ai-timesheet](https://sushantgawali.github.io/agentic-ai-timesheet/)**

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

Nine focused sub-agents run in a directed pipeline. Each calls MCP tools, writes output to shared state on disk, and passes a plain-text summary to the next phase.

```
audit_agent_sdk.py  (orchestrator)
        │
        ├── Phase 1 ──────────────────────────────────────────────────┐
        │   ├── Normalization Agent    → build_work_units             │
        │   │     reads:  timesheets, employees, assignments,         │
        │   │             leave (HR + calendar), projects, holidays   │  parallel
        │   ├── Contract Agent         → build_contract_model         │
        │   │     reads:  documents/sow/*.docx,                       │
        │   │             documents/guidelines/*.pdf                  │
        │   └── Context Mining Agent   → extract_slack_signals        │
        │         reads:  slack_activity.csv, timesheets              │
        │                                                              ┘
        │              writes to output/agent_state/ ──────────────────────────────┐
        │                     work_units.json                                       │
        │                     contract_model.json                                   │
        │                     slack_signals.json                                    │
        │                                                              ┌────────────┘
        ├── Phase 2                                                    │ flat-file JSON store
        │   └── Reconciliation Agent   → reconcile_work               │ full findings saved here;
        │         reads:  work_units.json + contract_model.json       │ tool responses return only
        │         writes: reconciled.json                              │ summaries to avoid context
        │                                                              │ overflow
        ├── Phase 3 ──────────────────────────────────────────────────┤
        │   ├── Revenue Leakage Agent  → detect_revenue_leakage       │  parallel
        │   │     reads:  reconciled.json + slack_signals.json        │
        │   │             + contract_model.json                        │
        │   │     writes: leakage_findings.json                        │
        │   └── Compliance Agent       → run_compliance_checks         │
        │         reads:  reconciled.json + contract_model.json       │
        │         writes: compliance_findings.json                     │
        │                                                              │
        ├── Phase 4                                                    │
        │   └── Invoice Drafting Agent → build_invoice_draft           │
        │         reads:  reconciled.json + contract_model.json       │
        │         writes: invoice_draft.json                           │
        │                                                              │
        ├── Phase 5                                                    │
        │   └── Review & Alert Agent  → generate_full_report ─────────┘
        │         reads:  all *.json state files
        │         writes: output/audit_*.html
        │
        └── Phase 6
            └── Digest Agent          → (no MCP tool)
                  reads:  all *_summary.txt caches
                  writes: ai_digest.json  (embedded in final report)
```

Each agent talks to `audit/mcp_server.py` over stdio (MCP protocol). State files persist across runs — if the pipeline crashes mid-way, set `RESUME=1` to skip phases that already have state files.

### Genuine agent loops

Three agents are not single-shot tool callers — they observe, decide, and re-query:

- **Contract Agent** — after loading SOWs, if a project is missing a billing rate or shows a suspicious rate, it calls `find_rate_for_member(project, member)` and `read_sow_section(project, query)` to re-read the contract and recover the real number instead of silently defaulting to `0.0`.
- **Context Mining (Slack) Agent** — a regex classifier handles the confident cases; messages the regex cannot decide surface as an `ambiguous_messages` bucket that the agent reads itself and batches back through `classify_ambiguous_messages`, so AI judgement (not just regex) drives the final Slack signals.
- **Review & Alert Agent** — instead of restating upstream summaries, it calls `get_leakage_findings`, `get_unlogged_signals`, and `compute_compound_exposure` to quantify cross-cutting patterns (e.g. the same person appearing in both leakage and unlogged-work signals) in USD before writing the executive insights.

Each loop has a `max_turns` budget (Contract/Slack: 10, Review: 15) so the agent can iterate without runaway tool calls.

---

## Report

The generated HTML report (`output/audit_*.html`) contains:

- **AI digest panel** — headline revenue risk, compliance blockers, invoice status, and priority actions
- **Intelligence panel** — top revenue risks, compliance blockers, quick wins, and critical human-review items
- **Key takeaways** — 5–7 AI-generated, specific, actionable insights
- **Revenue leakage** — grouped by type, each with USD impact estimate
- **Compliance blockers** — CRITICAL and WARNING findings with policy clause references
- **Unlogged Slack work** — messages that signal billable activity with no timesheet
- **Invoice draft** — line items by project with contract rates and flagged lines for review
- **Project budget vs actuals** — hours and cost against SOW limits
- **Audit checks** — 18 deterministic checks (invalid timestamps, overlaps, leave-day billing, etc.)
- **Data quality** — per-flag accordion tables with source file evidence

All sections are collapsible accordions with fixed-height scrollable tables and source file chips per finding.

---

## Quick start

### Run locally and publish to GitHub Pages

```bash
./run_local.sh          # uses data/v5, full run
./run_local.sh v3       # uses data/v3
RESUME=1 ./run_local.sh # skip agents whose state files already exist
```

Requires the Claude CLI (`claude login`) — no API key needed.

### Run directly with an API key

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
export DATA_DIR=data/v5
python3.11 audit_agent_sdk.py
# Report written to output/audit_v5_sonnet_YYYY-MM-DD.html
```

### Streamlit UI

```bash
python3.11 -m streamlit run app.py
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `data` | Path to the data folder |
| `OUT_DIR` | `output` | Where HTML report and agent state are written |
| `MODEL` | `claude-haiku-4-5-20251001` | Model for phases 1–4 |
| `REVIEW_MODEL` | `claude-sonnet-4-6` | Model for phase 5 (Review & Alert) |
| `RESUME` | `0` | Set to `1` to skip agents with existing state files |
| `STAGGER_DELAY` | `0` | Seconds between parallel agent launches (rate-limit guard) |

---

## Data sources

Drop any combination of CSVs into `DATA_DIR`. The loader scans column headers and infers each file's role automatically — no fixed filenames required.

| Role | Key columns |
|------|-------------|
| Timesheets | `user`, `date`, `hours`, `begin`, `end` |
| Employees | `user`, `hourly_rate` / `rate`, `status`, `contract_hrs` |
| Assignments | `user`, `project` |
| Leave | `user`, `date`, `leave_type`, `all_day` |
| Projects | `project`, `status`, `budget`, `end_date` |
| Slack | `user`, `date`, `text` / `channel` |
| Holidays | `date`, `holiday` / `name` |

SOW documents go in `DATA_DIR/documents/sow/` (`.docx`).
HR policy guidelines go in `DATA_DIR/documents/guidelines/` (`.pdf` or `.docx`).

---

## Project structure

```
.
├── audit_agent_sdk.py          # Orchestrator — runs 9 agents in 6 phases
├── app.py                      # Streamlit UI to run pipeline and view reports
├── run_local.sh                # Run pipeline and publish report to GitHub Pages
├── generate_index.py           # GitHub Pages index builder
│
├── audit/
│   ├── mcp_server.py           # stdio MCP server — exposes tools to agents
│   ├── loader.py               # File-agnostic CSV + DOCX loader
│   ├── checks.py               # 18 deterministic audit checks
│   ├── report_builder.py       # HTML report generator
│   ├── prompts.py              # Agent prompt strings and builder functions
│   ├── email_signals.py        # Email-based signal parser
│   └── tools/                  # MCP tool implementations (called by mcp_server.py)
│       ├── normalization.py    # Build WorkUnit records from timesheets
│       ├── contract.py         # Parse SOW + guidelines → ContractModel
│       ├── slack_mining.py     # Classify Slack messages → signals
│       ├── reconciliation.py   # Mark billable/non-billable, detect duplicates
│       ├── leakage.py          # Detect revenue leakage, estimate USD impact
│       ├── compliance.py       # Run compliance checks (CRITICAL/WARNING)
│       └── invoice.py          # Draft invoice line items with contract rates
│
├── data/
│   ├── v2/                     # Baseline dataset
│   ├── v3/                     # Extended dataset
│   └── v5/                     # Full dataset
│       ├── *.csv               # Timesheet, employee, assignment, leave, etc.
│       └── documents/
│           ├── sow/            # SOW DOCX files
│           └── guidelines/     # HR policy PDFs + DOCXs
│
├── output/                     # Generated reports (git-ignored)
│   └── agent_state/            # Inter-agent state JSON files (git-ignored)
│
└── requirements.txt
```
