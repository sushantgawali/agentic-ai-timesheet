# Claude Code Commands

Run the timesheet auditor interactively using Claude Code slash commands.
All logic runs locally with Python 3 stdlib — no external dependencies beyond Claude Code itself.

---

## How it works

```
/timesheet:load-data    →  validate data sources & print summary
/timesheet:audit        →  detect issues across 13 checks
/timesheet:propose-fixes → generate correction plan for review
/timesheet:apply-fixes  →  apply approved fixes to the CSV
```

Each command reads directly from the `data/` directory. The audit and
propose-fixes commands are always read-only. Only `apply-fixes` writes to
`kimai_timesheets.csv`, and it always creates a timestamped backup first.

---

## Prerequisites

- [Claude Code](https://claude.ai/code) CLI
- Python 3 (stdlib only — no pip required)
- 8 CSV files in the `data/` directory

---

## Commands

### `/timesheet:load-data`

Validates all 8 files exist and prints a structured summary of each data
source — employee list, project list, leave records, and timesheet overview.

```
/timesheet:load-data
```

Run this first to confirm your data is complete before auditing.

---

### `/timesheet:audit`

Runs 13 checks against `kimai_timesheets.csv` and outputs:
- **Summary** — total CRITICAL / WARNING / INFO issue counts
- **Issues table** — every issue as `User | Date | Issue`, sorted by severity
- **Detailed findings** — grouped by check code
- **HTML report** — written to `output/audit_YYYY-MM-DD.html`

```
/timesheet:audit
```

**Checks performed:**

| Severity | Check | What it detects |
|----------|-------|-----------------|
| CRITICAL | CHECK-1 | Invalid timestamp (`end` hour ≥ 24) |
| CRITICAL | CHECK-2 | Overlapping time entries for the same user on the same day |
| CRITICAL | CHECK-3 | Hours logged on an approved leave day |
| CRITICAL | CHECK-4 | Billing a project not assigned to the user |
| CRITICAL | CHECK-5 | Billing an archived project |
| WARNING  | CHECK-6 | Hourly rate differs from canonical HR rate |
| WARNING  | CHECK-7 | Missing `activity` field |
| WARNING  | CHECK-8 | Missing `description` field |
| WARNING  | CHECK-9 | Missing `project` field |
| WARNING  | CHECK-10 | Billing entry from a deactivated employee |
| INFO     | CHECK-11 | Entry on a weekend |
| INFO     | CHECK-12 | Slack/git activity detected but no timesheet entry that day |
| INFO     | CHECK-13 | Declared hours differ from `end − begin` by more than 9 minutes |

---

### `/timesheet:propose-fixes`

Re-reads all data and generates a structured correction plan without modifying
any files. Fixes are classified into four categories:

| Category | Applied by default | Description |
|----------|--------------------|-------------|
| **AUTO-APPLY** | Yes | High-confidence fixes (rate corrections, archived project recoding, activity inference from description, timestamp normalisation) |
| **OVERLAP FIXES** | Yes | Delete catch-all entries; trim partial overlaps |
| **NEEDS HUMAN REVIEW** | No (default shown) | Leave-day entries, missing descriptions, deactivated employee rows |
| **MISSING ENTRY ADDITIONS** | No | New rows for days with Slack/git activity but no timesheet |

```
/timesheet:propose-fixes
```

Review the plan before running `apply-fixes`.

---

### `/timesheet:apply-fixes`

Applies the correction plan to `kimai_timesheets.csv`. Always creates a
timestamped backup before writing.

```
/timesheet:apply-fixes
```
Applies only AUTO-APPLY and OVERLAP FIX changes.

```
/timesheet:apply-fixes --include-review-items
```
Also applies NEEDS_REVIEW defaults and inserts missing-entry rows.

**To restore from backup:**
```bash
cp data/kimai_timesheets.backup.<timestamp>.csv data/kimai_timesheets.csv
```

---

### `/commit-push`

Analyzes all staged and unstaged changes, writes a meaningful commit message,
and asks for confirmation before committing and pushing.

```
/commit-push
```

Supports three responses:
- **yes** — commit and push
- **edit** — provide a custom message, then re-confirm
- **no** — unstage everything, no changes made

---

## Typical workflow

```bash
# 1. Validate your data
/timesheet:load-data

# 2. See what's wrong
/timesheet:audit

# 3. Review the correction plan
/timesheet:propose-fixes

# 4a. Apply safe fixes only
/timesheet:apply-fixes

# 4b. Or apply everything (review defaults accepted)
/timesheet:apply-fixes --include-review-items

# 5. Re-audit to confirm issues are resolved
/timesheet:audit

# 6. Commit and push changes
/commit-push
```

---

## Relevant files

```
.claude/
└── commands/
    └── timesheet/
        ├── load-data.md       # /timesheet:load-data
        ├── audit.md           # /timesheet:audit
        ├── propose-fixes.md   # /timesheet:propose-fixes
        └── apply-fixes.md     # /timesheet:apply-fixes
    └── commit-push.md         # /commit-push
```
