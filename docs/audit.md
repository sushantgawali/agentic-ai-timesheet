# /timesheet:audit

## Overview

Runs 13 automated checks against `kimai_timesheets.csv`, cross-referencing
HR, project, Slack, and git data. Outputs a per-row issues table sorted by
severity, followed by detailed findings grouped by check.

---

## Usage

```
/timesheet:audit
```

No arguments. Read-only — does not modify any files.

### Example output

```
=== AUDIT REPORT — kimai_timesheets.csv — 2026-04-03 ===

SUMMARY
  Total entries audited : 159
  CRITICAL issues       :  13
  WARNING issues        :  28
  INFO issues           : 116

=== ISSUES TABLE ===
User      Date          Issue
--------------------------------------------------------------------------
john      2026-03-10    [CRITICAL] CHECK-3: Billed on approved leave day
bob       2026-03-16    [CRITICAL] CHECK-4: Unassigned project: 'Legacy Migration'
admin     2026-03-26    [WARNING]  CHECK-6: Wrong rate: 90 (canonical=100)
...
```

---

## Checks reference

### CRITICAL

| Check | Name | Description |
|-------|------|-------------|
| CHECK-1 | Invalid Timestamp | `begin` or `end` field has hour ≥ 24 (e.g. `T24:27:00`) |
| CHECK-2 | Overlapping Entries | Two entries for the same user on the same day have overlapping time ranges |
| CHECK-3 | Timesheet on Leave Day | Hours logged on a date that has an approved leave record |
| CHECK-4 | Unassigned Project Billing | User billed a project they are not assigned to in `hr_assignments.csv` |
| CHECK-5 | Archived Project Billing | User billed a project whose status is `archived` in `pm_projects.csv` |

### WARNING

| Check | Name | Description |
|-------|------|-------------|
| CHECK-6 | Inconsistent Hourly Rate | `hourly_rate` in the entry differs from the canonical rate in `hr_employees.csv` |
| CHECK-7 | Missing Activity | `activity` field is empty |
| CHECK-8 | Missing Description | `description` field is empty |
| CHECK-9 | Missing Project | `project` field is empty |
| CHECK-10 | Deactivated Employee Billing | Entry belongs to a user whose `status` is `deactivated` |

### INFO

| Check | Name | Description |
|-------|------|-------------|
| CHECK-11 | Weekend Entry | Entry falls on a Saturday or Sunday |
| CHECK-12 | Missing Timesheet — Active Day | User has Slack messages (> 5) or git commits but no timesheet entry that day |
| CHECK-13 | Hours Field Accuracy | Declared `hours` value differs from `end − begin` by more than 0.15h |

---

## Implementation

### Data flow

```
kimai_timesheets.csv  ─┐
hr_employees.csv       ├─► build lookup dicts ─► run checks ─► collect (user, date, check, brief, detail)
hr_assignments.csv     │
hr_leave.csv           │                                         │
pm_projects.csv        │                                         ▼
slack_activity.csv    ─┘                              issues table + detailed section
git_commits.csv       ─┘
```

### Issue storage

Each finding is stored as a tuple:
```python
(severity_order, user, date, check, severity_label, brief, full_detail)
```

This lets the same data drive both the **issues table** (sorted by severity → user → date)
and the **detailed section** (grouped by check code).

### Overlap detection (CHECK-2)

Entries are grouped by `(user, date)`, sorted by `begin`, then every pair is
tested for `begin_A < end_B and begin_B < end_A`. Duplicate pair reporting is
suppressed with a `seen` set keyed on `(min(rowA, rowB), max(rowA, rowB))`.

### Active-day detection (CHECK-12)

A day is considered "active" if Slack messages > 5 **or** git commits > 0.
Days on approved leave are excluded from this check.

### Hours accuracy threshold (CHECK-13)

A tolerance of **0.15h (9 minutes)** is used to avoid false positives from
rounding in the Kimai export. Rows with invalid timestamps (CHECK-1) are
skipped for this check.
