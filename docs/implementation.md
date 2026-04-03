# Agentic AI Timesheet — Implementation Overview

## Purpose

This project provides a set of Claude Code slash commands that audit
`data/kimai_timesheets.csv` against multiple HR, project, and activity data
sources, identify issues, propose fixes, and apply approved corrections. All
logic runs locally via Python 3 stdlib — no external dependencies.

---

## System Architecture

```
data/
├── kimai_timesheets.csv     ← primary file being audited & corrected
├── hr_employees.csv         ┐
├── hr_assignments.csv       │ reference data (read-only)
├── hr_leave.csv             │
├── pm_projects.csv          │
├── slack_activity.csv       │
├── git_commits.csv          │
└── calendar_events.csv      ┘

.claude/commands/timesheet/
├── load-data.md             ← /timesheet:load-data
├── audit.md                 ← /timesheet:audit
├── propose-fixes.md         ← /timesheet:propose-fixes
└── apply-fixes.md           ← /timesheet:apply-fixes
```

Each command is a markdown file containing a natural-language prompt and an
embedded Python script. Claude executes the script via the Bash tool and
formats the output for the user.

---

## Command Pipeline

```
/timesheet:load-data
        │
        │  validate files exist, print data summary
        ▼
/timesheet:audit
        │
        │  run 13 checks, output issues table + detailed findings
        ▼
/timesheet:propose-fixes
        │
        │  classify fixes into AUTO-APPLY / OVERLAP / NEEDS-REVIEW / ADDITIONS
        ▼
/timesheet:apply-fixes [--include-review-items]
        │
        │  backup → apply → validate → print change log
        ▼
   kimai_timesheets.csv  (corrected)
```

Each stage is independent — you can re-run any command at any time. The audit
and propose-fixes commands are always read-only.

---

## Data Model

### kimai_timesheets.csv

The primary file. One row per time entry.

| Column | Type | Description |
|--------|------|-------------|
| `user` | string | Username, FK to `hr_employees.username` |
| `date` | YYYY-MM-DD | Calendar date of the entry |
| `begin` | ISO 8601 datetime | Start time (`YYYY-MM-DDTHH:MM:SS`) |
| `end` | ISO 8601 datetime | End time (may have hour ≥ 24 — data quality issue) |
| `hours` | float | Declared duration (may differ from `end − begin`) |
| `project` | string | Project name, FK to `pm_projects.name` |
| `activity` | string | Activity type (e.g. Development, Testing) |
| `description` | string | Free-text entry description |
| `hourly_rate` | float | Rate billed (should match `hr_employees.rate`) |
| `submitted_at` | ISO 8601 datetime | When the entry was submitted |

### Reference data

| File | Key columns | Used for |
|------|-------------|----------|
| `hr_employees.csv` | `username`, `rate`, `status` | Rate validation, deactivated-user check |
| `hr_assignments.csv` | `user`, `project` | Authorised project billing check |
| `hr_leave.csv` | `user`, `date`, `status` | Leave-day billing check |
| `pm_projects.csv` | `name`, `status` | Archived project check |
| `slack_activity.csv` | `user`, `date`, `messages` | Active-day detection (> 5 messages) |
| `git_commits.csv` | `user`, `date`, `commits` | Active-day detection (> 0 commits) |

> **Column name quirks:** `pm_projects.csv` uses `name` (not `project_name`)
> and `hr_leave.csv` uses `type` (not `leave_type`). All scripts normalise
> these with `p.get('project_name') or p.get('name')`.

---

## Lookup Structures

Every script builds the same set of in-memory lookups from the reference CSVs:

```python
emp_rate   = {username: rate}          # canonical hourly rate per user
emp_status = {username: status}        # active / deactivated
user_projs = {user: {project, ...}}    # authorised projects per user
approved_leave = {(user, date), ...}   # approved leave day set
proj_status = {project_name: status}  # active / archived per project
slack_active = {(user, date): msgs}    # slack message count (>5 threshold)
git_active   = {(user, date): commits} # git commit count
```

These are rebuilt fresh on every command invocation — there is no shared state
between commands.

---

## Audit Checks

Checks are grouped into three severity levels:

### CRITICAL — data integrity failures
| ID | Condition |
|----|-----------|
| CHECK-1 | `end` timestamp has hour ≥ 24 |
| CHECK-2 | Two entries for the same user+date have overlapping time ranges |
| CHECK-3 | Entry exists on a day with an approved leave record |
| CHECK-4 | `project` not in user's authorised assignments |
| CHECK-5 | `project` has `status=archived` |

### WARNING — policy / completeness violations
| ID | Condition |
|----|-----------|
| CHECK-6 | `hourly_rate` ≠ canonical rate from HR |
| CHECK-7 | `activity` field is empty |
| CHECK-8 | `description` field is empty |
| CHECK-9 | `project` field is empty |
| CHECK-10 | Entry belongs to a user with `status=deactivated` |

### INFO — signals worth investigating
| ID | Condition |
|----|-----------|
| CHECK-11 | Entry falls on a weekend |
| CHECK-12 | Slack or git activity detected but no timesheet entry that day |
| CHECK-13 | Declared `hours` differs from `end − begin` by more than 0.15 h |

---

## Fix Classification

`/timesheet:propose-fixes` classifies every finding into one of four buckets:

| Bucket | Applied by default | Applied with `--include-review-items` |
|--------|--------------------|---------------------------------------|
| AUTO-APPLY | Yes | Yes |
| OVERLAP FIXES | Yes | Yes |
| NEEDS HUMAN REVIEW | No | Yes (using default option) |
| MISSING ENTRY ADDITIONS | No | Yes |

### Auto-apply confidence rules

An AUTO-APPLY fix is generated when the correct value can be determined
unambiguously from the reference data:

- **Rate correction** — single source of truth (`hr_employees.rate`)
- **Archived project recoding** — user has exactly one active assignment to fall back to
- **Activity inference** — description matches a keyword in a known category
- **Missing project (single assignment)** — only one possible value
- **Timestamp normalisation** — arithmetic (hour ≥ 24 → next-day time)

When confidence is lower (multiple possible values, or requires human judgement),
the fix is placed in NEEDS HUMAN REVIEW with a recommended default.

---

## Apply Safety Model

`/timesheet:apply-fixes` uses a two-phase approach:

**Phase 1 — collect**
Run the same detection logic as audit/propose-fixes, accumulating a list of
`(index, field, new_value, reason)` tuples and a set of row indices to delete.
No writes happen in this phase.

**Phase 2 — write**
1. Create a timestamped backup: `data/kimai_timesheets.backup.YYYYMMDD-HHMMSS.csv`
2. Apply all field changes to the in-memory row list
3. Filter out deleted rows
4. Append new rows (if `--include-review-items`)
5. Write the final list to `kimai_timesheets.csv`
6. Re-read the written file and run post-write sanity checks

**To restore from backup:**
```bash
cp data/kimai_timesheets.backup.<timestamp>.csv data/kimai_timesheets.csv
```

---

## Design Decisions

### Why Python stdlib only?
Commands run in whatever environment Claude Code is active in. Requiring no
`pip install` step means the commands work immediately on any machine.

### Why rebuild lookups on every command?
Avoids stale state between runs. The reference CSVs could be edited between
`audit` and `apply-fixes` (e.g. HR updates an assignment). Re-reading on every
invocation ensures the fix logic always reflects the current data.

### Why separate propose-fixes and apply-fixes?
The correction plan is a human review step. Separating proposal from
application means the user can inspect every change before it is written, and
can choose between conservative (AUTO-APPLY only) and aggressive
(`--include-review-items`) modes.

### Why store issues as `(user, date, check, severity, brief, detail)` tuples?
A single structured tuple supports two different output formats from the same
data: the **issues table** (sorted by severity, showing brief) and the
**detailed section** (grouped by check, showing full detail). No duplicate
detection logic is needed.

### Hours accuracy threshold (0.15 h = 9 min)
Kimai exports hours as rounded decimals. A strict equality check would flag
virtually every entry. 9 minutes covers typical rounding while still catching
genuine discrepancies (most real errors are 15–30+ minutes).
