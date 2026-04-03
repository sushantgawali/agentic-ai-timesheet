Generate a structured correction plan for all issues in `data/kimai_timesheets.csv`.
Re-reads all CSV data from disk. Does NOT modify any files.

## Instructions

Run the python3 script below via Bash, then present the CORRECTION PLAN to the user
for review before any changes are applied.

```python
import csv, os, sys, json
from datetime import datetime, timedelta, date as date_cls
from collections import defaultdict

DATA_DIR = "data"

def load(fname):
    with open(os.path.join(DATA_DIR, fname)) as f:
        return list(csv.DictReader(f))

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
proj_status = {(p.get('project_name') or p.get('name','')): p.get('status','').strip() for p in projects}
# Primary active project per user (first assigned active project)
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

auto_apply   = []  # list of dicts: {row, field, old, new, reason}
needs_review = []  # list of dicts: {row, options, default, reason}
additions    = []  # list of dicts: new row fields
deletions    = []  # list of dicts: {row, user, date, project, requires_confirmation, reason}

def row_id(i, row):
    return f"row{i}({row.get('user','')}|{row.get('date','')}|{row.get('begin','')[:16]})"

fmt = '%Y-%m-%dT%H:%M:%S'

for i, row in enumerate(ts, start=2):
    user    = row.get('user','').strip()
    date    = row.get('date','').strip()
    begin   = row.get('begin','').strip()
    end_val = row.get('end','').strip()
    hours   = row.get('hours','').strip()
    project = row.get('project','').strip()
    activity= row.get('activity','').strip()
    desc    = row.get('description','').strip()
    rate    = row.get('hourly_rate','').strip()

    # CHECK-1: Fix invalid timestamps (hour >= 24)
    if 'T' in end_val:
        time_part = end_val.split('T')[1]
        try:
            h = int(time_part.split(':')[0])
            if h >= 24:
                # Normalise: move excess hours into date
                mins = int(time_part.split(':')[1])
                secs = int(time_part.split(':')[2]) if len(time_part.split(':')) > 2 else 0
                total_mins = h * 60 + mins
                new_h = total_mins // 60 % 24
                extra_days = total_mins // (24 * 60)
                base_date = datetime.strptime(date, '%Y-%m-%d')
                new_end_dt = base_date + timedelta(days=extra_days, hours=new_h, minutes=mins % 60, seconds=secs)
                # But actually: T24:27 means 24h 27m past midnight of that day = next day 00:27
                new_end_str = new_end_dt.strftime(fmt)
                # Recalc hours
                try:
                    b_dt = datetime.strptime(begin, fmt)
                    calc_h = round((new_end_dt - b_dt).total_seconds() / 3600, 2)
                    auto_apply.append({'row': i, 'field': 'end', 'old': end_val, 'new': new_end_str,
                        'reason': f'Hour>=24 invalid; normalised to next-day time'})
                    auto_apply.append({'row': i, 'field': 'hours', 'old': hours, 'new': str(calc_h),
                        'reason': f'Recalculated after fixing end timestamp'})
                except ValueError:
                    pass
        except (ValueError, IndexError):
            pass

    # CHECK-3: Timesheet on leave day → needs review (default: delete)
    if (user, date) in approved_leave:
        needs_review.append({
            'row': i, 'user': user, 'date': date, 'project': project,
            'options': [
                'A: Delete this entry (leave days should not be billed)',
                'B: Cancel the leave record if work was actually performed (requires HR approval)'
            ],
            'default': 'A',
            'reason': f'{user} has approved leave on {date}'
        })

    # CHECK-4/5: Unassigned or archived project
    if project and project not in user_projs.get(user, set()):
        if proj_status.get(project,'') == 'archived':
            # Recode to primary active project
            primary = user_primary_active.get(user, '')
            if primary:
                auto_apply.append({'row': i, 'field': 'project', 'old': project, 'new': primary,
                    'reason': f'Project archived; recoded to {user}\'s primary active project'})
            else:
                needs_review.append({
                    'row': i, 'user': user, 'date': date, 'project': project,
                    'options': ['A: Remove row (no valid project to recode to)', 'B: Manually specify correct project'],
                    'default': 'A',
                    'reason': f'Archived project billing and no active assignment found'
                })
        else:
            needs_review.append({
                'row': i, 'user': user, 'date': date, 'project': project,
                'options': [
                    f'A: Recode to {user}\'s assigned projects: {sorted(user_projs.get(user,set()))}',
                    'B: Add retroactive HR assignment for this project'
                ],
                'default': 'A',
                'reason': f'{user} is not assigned to project {project!r}'
            })

    # CHECK-6: Fix wrong hourly rate
    canonical = emp_rate.get(user,'')
    if canonical and rate and rate != canonical:
        auto_apply.append({'row': i, 'field': 'hourly_rate', 'old': rate, 'new': canonical,
            'reason': f'Canonical rate for {user} is {canonical} per hr_employees.csv'})

    # CHECK-7: Missing activity — infer from description or flag
    if not activity:
        inferred = None
        d_lower = desc.lower()
        if any(w in d_lower for w in ['meeting','standup','sync','call','review session']):
            inferred = ('Meeting', 'HIGH')
        elif any(w in d_lower for w in ['design','wireframe','mockup','ui','ux']):
            inferred = ('Design', 'HIGH')
        elif any(w in d_lower for w in ['test','qa','bug','fix','hotfix']):
            inferred = ('Testing', 'HIGH')
        elif any(w in d_lower for w in ['develop','implement','code','build','feature','api','integration']):
            inferred = ('Development', 'HIGH')
        elif any(w in d_lower for w in ['doc','document','write','spec','report']):
            inferred = ('Documentation', 'MEDIUM')
        elif any(w in d_lower for w in ['review','pr','pull request','code review']):
            inferred = ('Code Review', 'MEDIUM')
        if inferred:
            auto_apply.append({'row': i, 'field': 'activity', 'old': '', 'new': inferred[0],
                'reason': f'Inferred from description ({inferred[1]} confidence): {desc[:50]!r}'})
        else:
            needs_review.append({
                'row': i, 'user': user, 'date': date, 'project': project,
                'options': ['A: Set to "General"', 'B: Manually specify activity'],
                'default': 'A',
                'reason': f'Cannot infer activity from description: {desc[:50]!r}'
            })

    # CHECK-8: Missing description
    if not desc:
        inferred_desc = None
        if activity and project:
            inferred_desc = f'{activity} work on {project}'
        if inferred_desc:
            needs_review.append({
                'row': i, 'user': user, 'date': date, 'project': project,
                'options': [f'A: Set description to "{inferred_desc}"', 'B: Leave as "[No description — please update]"'],
                'default': 'A',
                'reason': 'Missing description; inferred from activity+project'
            })
        else:
            auto_apply.append({'row': i, 'field': 'description', 'old': '', 'new': '[No description — please update]',
                'reason': 'Empty description; placeholder inserted'})

    # CHECK-9: Missing project — infer if user has single assignment
    if not project:
        assigned = list(user_projs.get(user, set()))
        if len(assigned) == 1:
            auto_apply.append({'row': i, 'field': 'project', 'old': '', 'new': assigned[0],
                'reason': f'{user} has only one project assignment ({assigned[0]}) — HIGH confidence'})
        else:
            needs_review.append({
                'row': i, 'user': user, 'date': date, 'project': '',
                'options': [f'A: Set to one of {assigned}', 'B: Manually specify project'],
                'default': 'A',
                'reason': f'Missing project; {user} has multiple assignments'
            })

    # CHECK-10: Deactivated employee — always needs human confirmation
    if emp_status.get(user,'') == 'deactivated':
        needs_review.append({
            'row': i, 'user': user, 'date': date, 'project': project,
            'options': [
                'A: Keep entry (deactivation may have been effective after this date)',
                'B: Delete entry (invalid billing from deactivated account)'
            ],
            'default': 'A',
            'reason': f'{user} has status=deactivated in hr_employees.csv'
        })

# CHECK-2 (overlaps): detect and propose fixes
by_user_date = defaultdict(list)
for i, row in enumerate(ts, start=2):
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
            by_user_date[(user, date)].append((i, b_dt, e_dt, row.get('project',''), row.get('activity',''), row))
        except ValueError:
            pass

overlap_fixes = []
for (user, date), entries in by_user_date.items():
    entries.sort(key=lambda x: x[1])
    for j in range(len(entries)):
        for k in range(j+1, len(entries)):
            ri, rb, re, rp, ra, rrow = entries[j]
            si, sb, se, sp, sa, srow = entries[k]
            if rb < se and sb < re and re != sb:
                overlap_min = round((min(re, se) - max(rb, sb)).total_seconds() / 60)
                # Heuristic: wider entry covering a narrower one → "catch-all" → propose deleting wider
                dur_j = (re - rb).total_seconds()
                dur_s = (se - sb).total_seconds()
                if dur_j > dur_s * 1.5 and sb >= rb and se <= re:
                    # j is the catch-all wrapper
                    overlap_fixes.append({
                        'type': 'delete_catchall',
                        'row': ri, 'user': user, 'date': date,
                        'project': rp, 'activity': ra,
                        'covered_by': si,
                        'reason': f'Wide entry row{ri} [{rb.strftime("%H:%M")}-{re.strftime("%H:%M")}] appears to be a catch-all superseded by row{si} [{sb.strftime("%H:%M")}-{se.strftime("%H:%M")} {sp}]'
                    })
                elif dur_s > dur_j * 1.5 and rb >= sb and re <= se:
                    overlap_fixes.append({
                        'type': 'delete_catchall',
                        'row': si, 'user': user, 'date': date,
                        'project': sp, 'activity': sa,
                        'covered_by': ri,
                        'reason': f'Wide entry row{si} [{sb.strftime("%H:%M")}-{se.strftime("%H:%M")}] appears to be a catch-all superseded by row{ri} [{rb.strftime("%H:%M")}-{re.strftime("%H:%M")} {rp}]'
                    })
                else:
                    # Partial overlap: trim earlier entry's end to later entry's begin
                    new_end = sb.strftime(fmt)
                    new_hours = round((sb - rb).total_seconds() / 3600, 2)
                    overlap_fixes.append({
                        'type': 'trim',
                        'row': ri, 'user': user, 'date': date,
                        'field': 'end', 'old': re.strftime(fmt), 'new': new_end,
                        'hours_new': str(new_hours),
                        'reason': f'Partial overlap {overlap_min}min with row{si}; trim row{ri} end to {sb.strftime("%H:%M")}'
                    })

# CHECK-12: Missing timesheet for active days
all_active = set(slack_active.keys()) | set(git_active.keys())
for (user, date) in sorted(all_active):
    if (user, date) not in ts_days and (user, date) not in approved_leave:
        primary = user_primary_active.get(user, '')
        additions.append({
            'user': user, 'date': date,
            'project': primary or '[UNKNOWN — please specify]',
            'activity': '[NEEDS_REVIEW]',
            'description': f'[Auto-detected: Slack msgs={slack_active.get((user,date),0)}, git commits={git_active.get((user,date),0)}]',
            'hourly_rate': emp_rate.get(user,''),
            'confidence': 'NEEDS_REVIEW',
            'reason': f'No timesheet entry despite Slack/Git activity (slack={slack_active.get((user,date),0)}, commits={git_active.get((user,date),0)})'
        })

# --- Print Correction Plan ---
today = date_cls.today().isoformat()
print(f"\n=== CORRECTION PLAN — {today} ===")

print(f"\nAUTO-APPLY CHANGES ({len(auto_apply)} changes, high-confidence):")
if auto_apply:
    for c in auto_apply:
        print(f"  [ROW {c['row']}] {c['field']}: {c['old']!r} → {c['new']!r}")
        print(f"           reason: {c['reason']}")
else:
    print("  None.")

print(f"\nOVERLAP FIXES ({len(overlap_fixes)} fixes, requires review):")
if overlap_fixes:
    for f in overlap_fixes:
        if f['type'] == 'delete_catchall':
            print(f"  [ROW {f['row']}] DELETE — {f['reason']}")
        else:
            print(f"  [ROW {f['row']}] TRIM {f['field']}: {f['old']!r} → {f['new']!r} (new hours={f['hours_new']})")
            print(f"           reason: {f['reason']}")
else:
    print("  None.")

print(f"\nCHANGES REQUIRING HUMAN REVIEW ({len(needs_review)} items):")
if needs_review:
    for n in needs_review:
        print(f"  [ROW {n['row']}] {n['user']} | {n['date']} | project={n['project']}")
        print(f"           reason: {n['reason']}")
        for opt in n['options']:
            marker = '* DEFAULT' if opt.startswith(n['default']) else '         '
            print(f"           {marker}  {opt}")
else:
    print("  None.")

print(f"\nMISSING ENTRY ADDITIONS ({len(additions)} rows — all NEEDS_REVIEW):")
if additions:
    for a in additions:
        print(f"  [NEW ROW] {a['user']} | {a['date']} | project={a['project']}")
        print(f"            {a['description']}")
        print(f"            reason: {a['reason']}")
else:
    print("  None.")

print("\n=== END CORRECTION PLAN ===")
```

After printing the plan, tell the user:
"Review the CORRECTION PLAN above.
- To apply only high-confidence AUTO-APPLY changes: run /timesheet:apply-fixes
- To apply everything including NEEDS_REVIEW items: run /timesheet:apply-fixes --include-review-items
- Original file will be backed up before any changes are made."
