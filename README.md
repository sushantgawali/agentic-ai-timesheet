# Agentic AI Timesheet Auditor

Audits, validates, and corrects Kimai timesheet exports using HR, project,
Slack, and git data as reference sources. Runs 13 checks and generates a
detailed HTML report with AI-generated key takeaways.

Two ways to use it:

| Approach | Best for | Doc |
|----------|----------|-----|
| **Claude Code commands** | Interactive local use — audit, plan fixes, apply | [docs/claude-code-commands.md](docs/claude-code-commands.md) |
| **Agent SDK pipeline** | Automated CI/CD — scheduled audits, GitHub Pages report hosting | [docs/agent-sdk-pipeline.md](docs/agent-sdk-pipeline.md) |

---

## Data sources

Place the following files in `data/` before running:

| File | Description |
|------|-------------|
| `kimai_timesheets.csv` | Primary timesheet export from Kimai |
| `hr_employees.csv` | Employee roles, canonical hourly rates, status |
| `hr_assignments.csv` | Which users are authorised to bill which projects |
| `hr_leave.csv` | Approved leave dates per user |
| `pm_projects.csv` | Project names, status (active/archived), budget hours |
| `slack_activity.csv` | Daily Slack message counts per user |
| `git_commits.csv` | Daily git commit counts per user |
| `calendar_events.csv` | Calendar events per user |

---

## Project structure

```
.
├── data/                          # CSV data sources
├── output/                        # Generated HTML reports
├── audit/
│   ├── loader.py                  # CSV loader with caching
│   ├── checks.py                  # All 13 audit checks
│   ├── report.py                  # HTML report generator
│   └── mcp_server.py              # Subprocess MCP server (Agent SDK)
├── audit_agent_sdk.py             # Agent SDK entry point (CI/CD)
├── audit_agent.py                 # Claude API entry point (alternative)
├── generate_index.py              # Builds GitHub Pages index
├── requirements.txt
├── .github/
│   └── workflows/
│       └── audit.yml              # GitHub Actions pipeline
├── docs/
│   ├── claude-code-commands.md    # Claude Code slash commands guide
│   ├── agent-sdk-pipeline.md      # Agent SDK CI/CD guide
│   ├── implementation.md
│   ├── load-data.md
│   ├── audit.md
│   ├── propose-fixes.md
│   └── apply-fixes.md
└── .claude/
    └── commands/
        └── timesheet/
            ├── load-data.md       # /timesheet:load-data
            ├── audit.md           # /timesheet:audit
            ├── propose-fixes.md   # /timesheet:propose-fixes
            └── apply-fixes.md     # /timesheet:apply-fixes
        └── commit-push.md         # /commit-push
```
