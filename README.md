# Agentic AI Timesheet Auditor

Audits, validates, and corrects Kimai timesheet exports using HR, project,
Slack, git, SOW contracts, and calendar data as reference sources. Runs 15
checks and generates a detailed HTML report with AI-generated key takeaways,
interactive filtering, per-employee/project summaries, and SOW budget vs
actuals analysis.

Two ways to use it:

| Approach | Best for | Doc |
|----------|----------|-----|
| **Claude Code commands** | Interactive local use — audit, plan fixes, apply | [docs/claude-code-commands.md](docs/claude-code-commands.md) |
| **Agent SDK pipeline** | Automated CI/CD — scheduled audits, GitHub Pages report hosting | [docs/agent-sdk-pipeline.md](docs/agent-sdk-pipeline.md) |

---

## Agent SDK flow

The audit runs as a 5-step agentic pipeline. Claude orchestrates tool calls
via an MCP subprocess server; no audit logic runs inside the LLM itself.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        audit_agent_sdk.py                           │
│                    (Claude Agent SDK entry point)                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  spawns subprocess MCP server
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       audit/mcp_server.py                           │
│                  (stdio MCP server — 5 tools)                       │
└──────┬──────────┬──────────┬──────────┬──────────────────┬──────────┘
       │          │          │          │                  │
       ▼          ▼          ▼          ▼                  ▼
  1. discover  2. read    3. load    4. run           5. generate
  _data_files  _sow_docs  _timesheet _audit_checks   _html_report
       │          │       _data           │                │
       │          │          │            │                │
       ▼          ▼          ▼            ▼                ▼
  Scan DATA_DIR  Parse    Load all     Run 15           Write HTML
  for all CSVs, .docx SOW  CSVs by    checks against   report to
  infer role    files in  inferred   loaded data.      output/.
  from columns. documents role       Return issues     Pass AI key
                /sow/.    (timesheet (CRITICAL /       takeaways
                Return    s, HR, PM, WARNING /         for the
                team,     Slack,     INFO).            summary
                rates,    calendar,                   section.
                monthly   holidays,
                hours.    emails).
```

**Data flow inside the MCP server:**

```
DATA_DIR/
  *.csv              →  loader.discover_csv_files()  →  role map
  documents/sow/*.docx → loader.load_sow_documents()  →  SOW structs
                       ↓
               loader.load_all()
                       ↓
         ctx {ts, emp_rate, emp_status, user_projs,
              approved_leave, proj_status, slack_active,
              git_active, public_holidays, calendar,
              proj_budget_hours, proj_budget_cost,
              proj_actual_hours, proj_actual_cost}
                       ↓
               checks.run_all(ctx)
                       ↓
         (issues[], hours_issues[])  →  report.generate()  →  audit_YYYY-MM-DD.html
```

---

## Data sources

The loader is **file-agnostic**: it scans the entire `DATA_DIR` directory,
reads column headers from every CSV, and infers each file's role automatically.
No fixed filenames are required — drop any combination of files and the loader
will pick them up.

### Inferred roles

| Role | Detected when columns include |
|------|-------------------------------|
| `timesheets` | `user`, `date`, `hours`, `begin`, `end` |
| `employees` | `user`, `hourly_rate` or `rate`, `status` |
| `assignments` | `user`, `project` (no `hours`) |
| `leave` | `user`, `date`, `leave_type` or `type` |
| `projects` | `project`, `status`, `budget` |
| `slack` | `user`, `date`, `messages` or `text`/`ts`/`channel` |
| `git` | `user`, `date`, `commits` |
| `calendar` | `user`, `date`, `event` or `summary` |
| `calendar_leave` | `user`, `date`, `leave` or `status` |
| `holidays` | `date`, `holiday` or `name` (no `user`) |
| `emails` | `from`, `to`, `subject` or `date`, `sender` |

### SOW documents

Place Statement of Work `.docx` files in `DATA_DIR/documents/sow/`. The loader
reads them with stdlib only (`zipfile` + `xml.etree.ElementTree` — no extra
pip dependency). Each SOW is parsed for:

- Project name, client, SOW reference, effective/end dates, monthly value
- Team table: member name, role, allocation %, contracted rate (USD/hr),
  monthly hours commitment

The `read_sow_documents` MCP tool also attaches actuals from the timesheets so
Claude can compare contracted hours/cost vs what was actually billed.

### Versioned datasets

```
data/
  v2/    # baseline dataset
  v3/    # extended dataset with additional employees and projects
  v5/    # full dataset: 9 CSVs + 17 SOW DOCXs + policy guidelines
    kimai_timesheets.csv
    hr_employees.csv
    hr_assignments.csv
    hr_leave.csv
    pm_projects.csv
    slack_activity.csv
    calendar_leave.csv
    calendar_holidays.csv
    emails.csv
    documents/
      sow/          # 17 Statement of Work DOCX files
      guidelines/   # HR policy PDFs and DOCXs (leave, holidays, timesheets)
```

---

## Audit checks

| Check | Name | Severity |
|-------|------|----------|
| CHECK-1  | INVALID TIMESTAMP | CRITICAL |
| CHECK-2  | OVERLAPPING ENTRIES | CRITICAL |
| CHECK-3  | TIMESHEET ON LEAVE DAY | CRITICAL |
| CHECK-4  | UNASSIGNED PROJECT BILLING | CRITICAL |
| CHECK-5  | ARCHIVED PROJECT BILLING | CRITICAL |
| CHECK-6  | INCONSISTENT HOURLY RATE | WARNING |
| CHECK-7  | MISSING ACTIVITY | WARNING |
| CHECK-8  | MISSING DESCRIPTION | WARNING |
| CHECK-9  | MISSING PROJECT | WARNING |
| CHECK-10 | DEACTIVATED EMPLOYEE BILLING | CRITICAL |
| CHECK-11 | WEEKEND ENTRIES | INFO |
| CHECK-12 | MISSING TIMESHEET — ACTIVE DAY | WARNING |
| CHECK-13 | HOURS FIELD ACCURACY | INFO |
| CHECK-14 | BILLING ON PUBLIC HOLIDAY | WARNING |
| CHECK-15 | PROJECT BUDGET OVERRUN | CRITICAL / WARNING |

CHECK-14 fires only when a `holidays` file is present. CHECK-15 fires per
project: CRITICAL if actual hours exceed budget, WARNING if >90%.

---

## Report sections

The generated HTML report includes:

- **Header** — data version, model used, run date
- **Summary tiles** — total entries, CRITICAL / WARNING / INFO counts
- **Key takeaways** — 3–5 AI-generated insight bullets
- **Check distribution chart** — horizontal bars by check name, coloured by severity
- **Top-10 leaderboard** — most-flagged employees and projects side by side
- **Employee summary** — all employees ranked by issue count (scrollable)
- **Project summary** — all projects ranked by issue count (scrollable)
- **Project budget vs actuals** — hours and cost budgets with progress bars (scrollable)
- **Issues table** — all findings with interactive severity / check / user / project filters (scrollable)
- **Hours field accuracy** — row-level declared vs calculated hour discrepancies (scrollable)

---

## Project structure

```
.
├── data/                          # Versioned CSV data sources + SOW documents
│   ├── v2/
│   ├── v3/
│   └── v5/
│       └── documents/
│           ├── sow/               # SOW DOCX files
│           └── guidelines/       # HR policy documents
├── output/                        # Generated HTML reports (git-ignored)
├── audit/
│   ├── loader.py                  # File-agnostic CSV + DOCX loader with caching
│   ├── checks.py                  # All 15 audit checks
│   ├── report.py                  # HTML report generator (charts, tables, filters)
│   └── mcp_server.py              # Subprocess MCP server — 5 tools over stdio
├── audit_agent_sdk.py             # Agent SDK entry point (CI/CD)
├── generate_index.py              # Builds GitHub Pages index
├── requirements.txt
├── .github/
│   └── workflows/
│       └── audit.yml              # GitHub Actions pipeline (v2/v3/v5 options)
├── docs/
│   ├── claude-code-commands.md    # Claude Code slash commands guide
│   └── agent-sdk-pipeline.md     # Agent SDK CI/CD guide
└── .claude/
    └── commands/
        └── timesheet/
            ├── load-data.md       # /timesheet:load-data
            ├── audit.md           # /timesheet:audit
            ├── propose-fixes.md   # /timesheet:propose-fixes
            └── apply-fixes.md     # /timesheet:apply-fixes
        └── commit-push.md         # /commit-push
```

---

## Quick start

### Agent SDK (CI/CD)

```bash
pip install claude-agent-sdk mcp anyio
export ANTHROPIC_API_KEY=sk-...
export DATA_VERSION=v5   # v2 | v3 | v5
python audit_agent_sdk.py
# Report written to output/audit_YYYY-MM-DD.html
```

### Claude Code commands (interactive)

```
/timesheet:load-data
/timesheet:audit
/timesheet:propose-fixes
/timesheet:apply-fixes
```

### GitHub Actions

Trigger manually via **Actions → Timesheet Audit → Run workflow**, select the
data version (v2 / v3 / v5), and the report is published to GitHub Pages.
