# /timesheet:propose-fixes

## Overview

Re-reads all data sources and generates a structured correction plan for every
CRITICAL and WARNING issue found. Organises fixes into four categories by
confidence level. Does **not** modify any files — output is for review only.

---

## Usage

```
/timesheet:propose-fixes
```

No arguments. Read-only — does not modify any files.

Run `/timesheet:apply-fixes` after reviewing to apply the changes.

### Example output

```
=== CORRECTION PLAN — 2026-04-03 ===

--- AUTO-APPLY CHANGES (18 changes, high-confidence) ---
  Row   35  john    2026-03-24    end       '2026-03-24T24:27:00' → '2026-03-25T00:27:00'
                                  ↳ Hour>=24 invalid; normalised to next-day time
  Row   90  admin   2026-03-09    project   'Legacy Migration' → 'ERP Integration'
                                  ↳ Project archived; recoded to admin's primary active project
  ...

--- OVERLAP FIXES (3 fixes, requires review) ---
  Row  25  john    2026-03-17    DELETE
                                  ↳ Wide catch-all entry superseded by row26 and row27
  ...

--- NEEDS HUMAN REVIEW (17 items) ---
  Row  17  john    2026-03-10    project=Website Redesign
                                  ↳ john has approved leave on 2026-03-10
                                  ★ DEFAULT  A: Delete this entry
                                             B: Cancel the leave record (requires HR approval)
  ...

--- MISSING ENTRY ADDITIONS (17 rows — all NEEDS_REVIEW) ---
  NEW ROW  alice   2026-03-09    project=Website Redesign  rate=80
                                  ↳ No timesheet despite Slack activity (slack=22, commits=0)
```

---

## Fix categories

### AUTO-APPLY
High-confidence fixes applied automatically by `/timesheet:apply-fixes`:

| Trigger | Fix |
|---------|-----|
| CHECK-1: hour ≥ 24 | Normalise timestamp to next-day time; recalculate `hours` |
| CHECK-4/5: archived project | Recode `project` to user's primary active assignment |
| CHECK-6: wrong rate | Set `hourly_rate` to canonical value from `hr_employees.csv` |
| CHECK-7: missing activity | Infer from description keywords (see table below) |
| CHECK-8: missing description (no activity/project) | Insert placeholder `[No description — please update]` |
| CHECK-9: missing project, single assignment | Set to user's only assigned project (HIGH confidence) |

**Activity inference keywords:**

| Activity | Keywords matched in description |
|----------|--------------------------------|
| Meeting | meeting, standup, sync, call, review session |
| Design | design, wireframe, mockup, ui, ux |
| Testing | test, qa, bug, fix, hotfix |
| Development | develop, implement, code, build, feature, api, integration |
| Documentation | doc, document, write, spec, report |
| Code Review | review, pr, pull request, code review |

### OVERLAP FIXES
Applied automatically. Two heuristics:

- **Delete catch-all**: if one entry spans > 1.5× the duration of another and
  fully contains it, the wider entry is treated as a catch-all and deleted.
- **Trim**: for partial overlaps, the earlier entry's `end` is trimmed to the
  start of the later entry; `hours` is recalculated.

### NEEDS HUMAN REVIEW
Require a human decision before applying. Each item shows a default option
(★) that `/timesheet:apply-fixes --include-review-items` will use:

| Trigger | Default action |
|---------|---------------|
| CHECK-3: entry on leave day | A — Delete the entry |
| CHECK-7: activity uninferable | A — Set to "General" |
| CHECK-8: missing description with activity+project | A — Set to inferred "{activity} work on {project}" |
| CHECK-9: missing project, multiple assignments | A — Set to first alphabetical assignment |
| CHECK-10: deactivated employee | A — Keep entry (deactivation date may post-date the entry) |

### MISSING ENTRY ADDITIONS
New rows proposed for days where Slack/git activity was detected but no
timesheet entry exists. All are `NEEDS_REVIEW`. Only added when running
`/timesheet:apply-fixes --include-review-items`.

---

## Implementation

### Primary active project resolution

For archived-project recoding and missing-entry additions, the script picks
each user's **primary active project** — the alphabetically first project that
is both assigned to the user and has `status=active` in `pm_projects.csv`.

### Overlap fix heuristic

```
dur_j = end_j - begin_j
dur_s = end_s - begin_s

if dur_j > dur_s * 1.5 and begin_s >= begin_j and end_s <= end_j:
    → delete row_j (catch-all)
elif dur_s > dur_j * 1.5 and begin_j >= begin_s and end_j <= end_s:
    → delete row_s (catch-all)
else:
    → trim row_j end to begin_s
```
