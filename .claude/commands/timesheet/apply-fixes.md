Apply approved corrections to `data/kimai_timesheets.csv`.

## Arguments

`$ARGUMENTS` may contain `--include-review-items` to also apply items that were
marked NEEDS_REVIEW in the correction plan. If absent, only AUTO-APPLY items are applied.

## Instructions

### Step 1 — Create a timestamped backup

Run via Bash:
```bash
ts=$(date +%Y%m%d-%H%M%S)
cp data/kimai_timesheets.csv "data/kimai_timesheets.backup.${ts}.csv"
echo "Backup created: data/kimai_timesheets.backup.${ts}.csv"
```

Print the backup filename so the user knows where to restore from.

### Step 2 — Apply corrections via python3

Run the following script via Bash. Pass the ARGUMENTS as an environment variable:

```python
import csv, os, sys, copy
from datetime import datetime, timedelta, date as date_cls
from collections import defaultdict

INCLUDE_REVIEW = "--include-review-items" in os.environ.get("APPLY_ARGS", "")
DATA_DIR = "data"
INFILE  = os.path.join(DATA_DIR, "kimai_timesheets.csv")

def load(fname):
    with open(os.path.join(DATA_DIR, fname)) as f:
        return list(csv.DictReader(f))

# Read original
with open(INFILE, newline='') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    original = list(reader)

ts        = load("kimai_timesheets.csv")
employees = load("hr_employees.csv")
assigns   = load("hr_assignments.csv")
leaves    = load("hr_leave.csv")
projects  = load("pm_projects.csv")
slack     = load("slack_activity.csv")
commits   = load("git_commits.csv")

emp_rate   = {e['username']: e.get('rate','').strip() for e in employees}
emp_status = {e['username']: e.get('status','').strip() for e in employees}
user_projs = defaultdict(set)
for a in assigns:
    user_projs[a['user']].add(a['project'])
approved_leave = set()
for l in leaves:
    if l.get('status','').strip().lower() == 'approved':
        approved_leave.add((l['user'], l['date']))
proj_status = {p['project_name']: p.get('status','').strip() for p in projects}
user_primary_active = {}
for u, projs in user_projs.items():
    active = [p for p in projs if proj_status.get(p,'') == 'active']
    if active:
        user_primary_active[u] = sorted(active)[0]

slack_active = defaultdict(int)
for s in slack:
    try:
        if int(s.get('messages', 0)) > 5:
            slack_active[(s['user'], s['date'])] += int(s['messages'])
    except ValueError:
        pass
git_active = defaultdict(int)
for g in commits:
    try:
        if int(g.get('commits', 0)) > 0:
            git_active[(g['user'], g['date'])] += int(g['commits'])
    except ValueError:
        pass

ts_days = set((r['user'], r['date']) for r in ts)

# Work on a mutable copy (0-indexed internally, row numbers in logs are 1-indexed from header=row1)
rows = [copy.copy(r) for r in original]
rows_to_delete = set()  # 0-based indices
new_rows = []
change_log = []
fmt = '%Y-%m-%dT%H:%M:%S'

def apply(idx, field, new_val, reason):
    old_val = rows[idx].get(field, '')
    if old_val != new_val:
        rows[idx][field] = new_val
        change_log.append(f"CHANGED  row{idx+2}: {field} {old_val!r} → {new_val!r}  ({reason})")

def delete_row(idx, reason):
    rows_to_delete.add(idx)
    r = rows[idx]
    change_log.append(f"DELETED  row{idx+2}: {r.get('user','')} {r.get('date','')} {r.get('project','')}  ({reason})")

for i, row in enumerate(rows):
    user    = row.get('user','').strip()
    date    = row.get('date','').strip()
    begin   = row.get('begin','').strip()
    end_val = row.get('end','').strip()
    hours   = row.get('hours','').strip()
    project = row.get('project','').strip()
    activity= row.get('activity','').strip()
    desc    = row.get('description','').strip()
    rate    = row.get('hourly_rate','').strip()

    # CHECK-1: Fix invalid timestamps
    if 'T' in end_val:
        time_part = end_val.split('T')[1]
        try:
            h = int(time_part.split(':')[0])
            if h >= 24:
                mins_part = time_part.split(':')[1]
                secs_part = time_part.split(':')[2] if len(time_part.split(':')) > 2 else '00'
                total_secs = h * 3600 + int(mins_part) * 60 + int(secs_part)
                base_date = datetime.strptime(date, '%Y-%m-%d')
                new_end_dt = base_date + timedelta(seconds=total_secs)
                new_end_str = new_end_dt.strftime(fmt)
                apply(i, 'end', new_end_str, 'invalid hour>=24 normalised')
                if begin:
                    try:
                        b_dt = datetime.strptime(begin, fmt)
                        calc_h = round((new_end_dt - b_dt).total_seconds() / 3600, 2)
                        apply(i, 'hours', str(calc_h), 'recalculated after end timestamp fix')
                    except ValueError:
                        pass
        except (ValueError, IndexError):
            pass

    # CHECK-3: Leave day entries (INCLUDE_REVIEW only)
    if INCLUDE_REVIEW and (user, date) in approved_leave:
        delete_row(i, f'timesheet entry on approved leave day (default: delete)')

    # CHECK-4/5: Archived or unassigned project
    if project and project not in user_projs.get(user, set()):
        if proj_status.get(project,'') == 'archived':
            primary = user_primary_active.get(user, '')
            if primary:
                apply(i, 'project', primary, f'archived project recoded to primary active project')
        elif INCLUDE_REVIEW:
            assigned = sorted(user_projs.get(user, set()))
            if len(assigned) == 1:
                apply(i, 'project', assigned[0], f'unassigned project; only one assignment available')

    # CHECK-6: Fix wrong hourly rate
    canonical = emp_rate.get(user,'')
    if canonical and rate and rate != canonical:
        apply(i, 'hourly_rate', canonical, f'rate corrected to canonical value from hr_employees')

    # CHECK-7: Missing activity
    if not activity:
        d_lower = desc.lower()
        inferred = None
        if any(w in d_lower for w in ['meeting','standup','sync','call','review session']):
            inferred = 'Meeting'
        elif any(w in d_lower for w in ['design','wireframe','mockup','ui','ux']):
            inferred = 'Design'
        elif any(w in d_lower for w in ['test','qa','bug','fix','hotfix']):
            inferred = 'Testing'
        elif any(w in d_lower for w in ['develop','implement','code','build','feature','api','integration']):
            inferred = 'Development'
        elif any(w in d_lower for w in ['doc','document','write','spec','report']):
            inferred = 'Documentation'
        elif any(w in d_lower for w in ['review','pr','pull request','code review']):
            inferred = 'Code Review'
        if inferred:
            apply(i, 'activity', inferred, 'inferred from description (HIGH confidence)')
        elif INCLUDE_REVIEW:
            apply(i, 'activity', 'General', 'missing activity; set to General (NEEDS_REVIEW)')

    # CHECK-8: Missing description
    if not desc:
        if activity and project:
            if INCLUDE_REVIEW:
                apply(i, 'description', f'{activity} work on {project}', 'inferred from activity+project')
        else:
            apply(i, 'description', '[No description — please update]', 'empty description; placeholder inserted')

    # CHECK-9: Missing project
    if not project:
        assigned = list(user_projs.get(user, set()))
        if len(assigned) == 1:
            apply(i, 'project', assigned[0], f'single-assignment inference ({assigned[0]})')
        elif INCLUDE_REVIEW and assigned:
            apply(i, 'project', sorted(assigned)[0], f'multiple assignments; defaulted to first alphabetically — NEEDS_REVIEW')

# CHECK-2: Overlapping entries
by_user_date = defaultdict(list)
for i, row in enumerate(rows):
    if i in rows_to_delete:
        continue
    user = row.get('user','').strip()
    date = row.get('date','').strip()
    begin = row.get('begin','').strip()
    end_v = row.get('end','').strip()
    if begin and end_v and 'T' in begin and 'T' in end_v:
        try:
            bh = int(begin.split('T')[1].split(':')[0])
            eh = int(end_v.split('T')[1].split(':')[0])
            if bh >= 24 or eh >= 24:
                continue
            b_dt = datetime.strptime(begin, fmt)
            e_dt = datetime.strptime(end_v, fmt)
            by_user_date[(user, date)].append((i, b_dt, e_dt, row.get('project',''), row.get('activity','')))
        except ValueError:
            pass

for (user, date), entries in by_user_date.items():
    entries.sort(key=lambda x: x[1])
    processed_deletions = set()
    for j in range(len(entries)):
        for k in range(j+1, len(entries)):
            ri, rb, re, rp, ra = entries[j]
            si, sb, se, sp, sa = entries[k]
            if ri in rows_to_delete or si in rows_to_delete:
                continue
            if rb < se and sb < re and re != sb:
                dur_j = (re - rb).total_seconds()
                dur_s = (se - sb).total_seconds()
                if dur_j > dur_s * 1.5 and sb >= rb and se <= re:
                    if ri not in processed_deletions:
                        delete_row(ri, f'catch-all overlap with row{si+2}; superseded by specific entry')
                        processed_deletions.add(ri)
                elif dur_s > dur_j * 1.5 and rb >= sb and re <= se:
                    if si not in processed_deletions:
                        delete_row(si, f'catch-all overlap with row{ri+2}; superseded by specific entry')
                        processed_deletions.add(si)
                else:
                    # Trim: shorten earlier entry to not overlap with later
                    new_end = sb.strftime(fmt)
                    new_hours = round((sb - rb).total_seconds() / 3600, 2)
                    apply(ri, 'end', new_end, f'partial overlap with row{si+2}; trimmed end to {sb.strftime("%H:%M")}')
                    apply(ri, 'hours', str(new_hours), 'recalculated after overlap trim')

# CHECK-12: Add missing entries (INCLUDE_REVIEW only)
if INCLUDE_REVIEW:
    all_active = set(slack_active.keys()) | set(git_active.keys())
    for (user, date) in sorted(all_active):
        if (user, date) not in ts_days and (user, date) not in approved_leave:
            primary = user_primary_active.get(user, '')
            new_rows.append({
                'user': user,
                'date': date,
                'begin': '',
                'end': '',
                'hours': '',
                'project': primary or '[UNKNOWN — please specify]',
                'activity': '[NEEDS_REVIEW]',
                'description': f'[Auto-detected: Slack msgs={slack_active.get((user,date),0)}, git commits={git_active.get((user,date),0)}]',
                'hourly_rate': emp_rate.get(user,''),
                'submitted_at': '',
            })
            change_log.append(f"ADDED    new row: {user} {date} {primary}  (detected Slack/Git activity)")

# Write output
final_rows = [r for i, r in enumerate(rows) if i not in rows_to_delete] + new_rows

with open(INFILE, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(final_rows)

# --- Verification ---
print(f"\n=== APPLY RESULTS ===")
print(f"  Original rows : {len(original)}")
print(f"  Deleted       : {len(rows_to_delete)}")
print(f"  Added         : {len(new_rows)}")
print(f"  Final rows    : {len(final_rows)}")
print(f"  Changes made  : {len(change_log)}")

print(f"\n--- CHANGE LOG ---")
for entry in change_log:
    print(f"  {entry}")

# Sanity checks
errors = []
with open(INFILE, newline='') as f:
    reader = csv.DictReader(f)
    final_check = list(reader)

for i, r in enumerate(final_check, start=2):
    if not r.get('user','').strip():
        errors.append(f"Row {i}: empty user field")
    end_v = r.get('end','').strip()
    if 'T' in end_v:
        try:
            h = int(end_v.split('T')[1].split(':')[0])
            if h >= 24:
                errors.append(f"Row {i}: still has invalid timestamp {end_v}")
        except (ValueError, IndexError):
            pass

if errors:
    print(f"\nWARNING — {len(errors)} post-write validation error(s):")
    for e in errors:
        print(f"  {e}")
else:
    print(f"\nPost-write validation: PASSED (no critical errors found)")

print(f"\n=== END APPLY RESULTS ===")
```

To pass the ARGUMENTS flag, run the script with:
```bash
APPLY_ARGS="$ARGUMENTS" python3 -c "$(cat <<'PYEOF'
... script above ...
PYEOF
)"
```

### Step 3 — Print next steps

After the script completes, print:

```
Corrections applied successfully.
Original backed up as data/kimai_timesheets.backup.[timestamp].csv

To verify the result run: /timesheet:audit
To restore the original: cp data/kimai_timesheets.backup.[timestamp].csv data/kimai_timesheets.csv
```
