Perform a comprehensive audit of `data/kimai_timesheets.csv` against all supporting
data sources. Do NOT modify any files.

## Instructions

Run the python3 script below via Bash (stdlib only). Then print the full AUDIT REPORT.

```python
import csv, os, sys, html
from datetime import datetime, timedelta
from collections import defaultdict

DATA_DIR  = "data"
OUT_DIR   = "output"

os.makedirs(OUT_DIR, exist_ok=True)

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

# Build lookup dicts
emp_rate   = {e['username']: e.get('rate','').strip() for e in employees}
emp_status = {e['username']: e.get('status','').strip() for e in employees}

user_projs = defaultdict(set)
for a in assigns:
    user_projs[a['user']].add(a['project'])

approved_leave = set()
for l in leaves:
    if l.get('status','').strip().lower() == 'approved':
        approved_leave.add((l['user'], l['date']))

proj_status = {}
for p in projects:
    pname = p.get('project_name') or p.get('name', '')
    proj_status[pname] = p.get('status', '').strip()

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

# all_issues = [(severity_order, user, date, check, severity_label, brief, full_detail)]
all_issues = []
# issues[check] = [(user, full_detail)]  — for detailed section
issues = defaultdict(list)
# structured rows for the hours accuracy table
hours_issues = []

SEV = {'CRITICAL': 0, 'WARNING': 1, 'INFO': 2}

def add(user, date, check, severity, brief, full_detail):
    all_issues.append((SEV[severity], user, date, check, severity, brief, full_detail))
    issues[check].append((user, full_detail))

for i, row in enumerate(ts, start=2):
    user    = row.get('user','').strip()
    date    = row.get('date','').strip()
    begin   = row.get('begin','').strip()
    end     = row.get('end','').strip()
    hours   = row.get('hours','').strip()
    project = row.get('project','').strip()
    activity= row.get('activity','').strip()
    desc    = row.get('description','').strip()
    rate    = row.get('hourly_rate','').strip()

    # CHECK-1: Invalid timestamp (hour >= 24)
    for field_name, val in [('begin', begin), ('end', end)]:
        if 'T' in val:
            time_part = val.split('T')[1]
            try:
                h = int(time_part.split(':')[0])
                if h >= 24:
                    add(user, date, 'CHECK-1', 'CRITICAL',
                        f"Invalid timestamp: {field_name}={val}",
                        f"  Row {i}: {user} | {date} | {field_name}={val}")
            except (ValueError, IndexError):
                add(user, date, 'CHECK-1', 'CRITICAL',
                    f"Unparseable timestamp: {field_name}={val}",
                    f"  Row {i}: {user} | {date} | {field_name}={val} (unparseable)")

    # CHECK-3: Timesheet on approved leave day
    if (user, date) in approved_leave:
        add(user, date, 'CHECK-3', 'CRITICAL',
            f"Billed on approved leave day — project={project}",
            f"  Row {i}: {user} | {date} | project={project}")

    # CHECK-4 & CHECK-5: Unassigned / archived project
    if project:
        if project not in user_projs.get(user, set()):
            add(user, date, 'CHECK-4', 'CRITICAL',
                f"Unassigned project: '{project}'",
                f"  Row {i}: {user} billed {project!r} | assigned={sorted(user_projs.get(user,set()))}")
        if proj_status.get(project,'') == 'archived':
            add(user, date, 'CHECK-5', 'CRITICAL',
                f"Archived project: '{project}'",
                f"  Row {i}: {user} | {date} | project={project} (archived)")

    # CHECK-6: Wrong hourly rate
    canonical = emp_rate.get(user,'')
    if canonical and rate and rate != canonical:
        add(user, date, 'CHECK-6', 'WARNING',
            f"Wrong rate: {rate} (canonical={canonical})",
            f"  Row {i}: {user} | rate={rate} | canonical={canonical}")

    # CHECK-7: Missing activity
    if not activity:
        add(user, date, 'CHECK-7', 'WARNING',
            f"Missing activity — desc={desc[:35]!r}",
            f"  Row {i}: {user} | {date} | project={project} | desc={desc[:40]!r}")

    # CHECK-8: Missing description
    if not desc:
        add(user, date, 'CHECK-8', 'WARNING',
            f"Missing description — activity={activity or '(none)'}",
            f"  Row {i}: {user} | {date} | project={project} | activity={activity}")

    # CHECK-9: Missing project
    if not project:
        add(user, date, 'CHECK-9', 'WARNING',
            f"Missing project — activity={activity}",
            f"  Row {i}: {user} | {date} | activity={activity}")

    # CHECK-10: Deactivated employee
    if emp_status.get(user,'') == 'deactivated':
        add(user, date, 'CHECK-10', 'WARNING',
            f"Deactivated employee billing — project={project}",
            f"  Row {i}: {user} | {date} | project={project}")

    # CHECK-11: Weekend entries
    try:
        d = datetime.strptime(date, '%Y-%m-%d')
        if d.weekday() >= 5:
            add(user, date, 'CHECK-11', 'INFO',
                f"Weekend entry ({d.strftime('%A')}) — project={project}",
                f"  Row {i}: {user} | {date} ({d.strftime('%A')}) | project={project} | desc={desc[:40]!r}")
    except ValueError:
        pass

    # CHECK-13: Hours accuracy
    skip_accuracy = any('T' in v and int(v.split('T')[1].split(':')[0]) >= 24
                        for v in [begin, end] if 'T' in v)
    if not skip_accuracy and begin and end and hours:
        try:
            fmt = '%Y-%m-%dT%H:%M:%S'
            b = datetime.strptime(begin, fmt)
            e_dt = datetime.strptime(end, fmt)
            if e_dt < b:
                e_dt += timedelta(days=1)
            calc = round((e_dt - b).total_seconds() / 3600, 2)
            declared = round(float(hours), 2)
            if abs(declared - calc) > 0.15:
                diff = round(declared - calc, 2)
                add(user, date, 'CHECK-13', 'INFO',
                    f"Hours mismatch: declared={declared}h vs calc={calc}h (diff={diff}h)",
                    f"  Row {i}: {user} | {date} | declared={declared}h calculated={calc}h diff={diff}h")
                hours_issues.append({'row': i, 'user': user, 'date': date, 'project': project, 'activity': activity, 'declared': declared, 'calc': calc, 'diff': diff})
        except (ValueError, TypeError):
            pass

# CHECK-2: Overlapping entries
by_user_date = defaultdict(list)
for i, row in enumerate(ts, start=2):
    user  = row.get('user','').strip()
    date  = row.get('date','').strip()
    begin = row.get('begin','').strip()
    end   = row.get('end','').strip()
    if begin and end and 'T' in begin and 'T' in end:
        try:
            fmt = '%Y-%m-%dT%H:%M:%S'
            b_h = int(begin.split('T')[1].split(':')[0])
            e_h = int(end.split('T')[1].split(':')[0])
            if b_h >= 24 or e_h >= 24:
                continue
            b_dt = datetime.strptime(begin, fmt)
            e_dt = datetime.strptime(end, fmt)
            by_user_date[(user, date)].append((i, b_dt, e_dt, row.get('project',''), row.get('activity','')))
        except ValueError:
            pass

for (user, date), entries in by_user_date.items():
    entries.sort(key=lambda x: x[1])
    seen = set()
    for j in range(len(entries)):
        for k in range(j+1, len(entries)):
            ri, rb, re, rp, ra = entries[j]
            si, sb, se, sp, sa = entries[k]
            if rb < se and sb < re and re != sb:
                key = (min(ri,si), max(ri,si))
                if key in seen:
                    continue
                seen.add(key)
                overlap_min = round((min(re, se) - max(rb, sb)).total_seconds() / 60)
                brief  = f"Overlap {overlap_min}min — row{ri}=[{rb.strftime('%H:%M')}-{re.strftime('%H:%M')} {rp}] vs row{si}=[{sb.strftime('%H:%M')}-{se.strftime('%H:%M')} {sp}]"
                detail = f"  Rows {ri}&{si}: {user} | {date} | overlap={overlap_min}min | row{ri}=[{rb.strftime('%H:%M')}-{re.strftime('%H:%M')} {rp}] row{si}=[{sb.strftime('%H:%M')}-{se.strftime('%H:%M')} {sp}]"
                add(user, date, 'CHECK-2', 'CRITICAL', brief, detail)

# CHECK-12: Active days with no timesheet
ts_days = set((r['user'], r['date']) for r in ts)
all_active = set(slack_active.keys()) | set(git_active.keys())
for (user, date) in sorted(all_active):
    if (user, date) not in ts_days and (user, date) not in approved_leave:
        msgs    = slack_active.get((user,date),0)
        commits = git_active.get((user,date),0)
        add(user, date, 'CHECK-12', 'WARNING',
            f"Active but no timesheet — slack={msgs} msgs, git={commits} commits",
            f"  {user} | {date} | slack_msgs={msgs} git_commits={commits}")

# --- Print Report ---
critical_checks = ['CHECK-1','CHECK-2','CHECK-3','CHECK-4','CHECK-5']
warning_checks  = ['CHECK-6','CHECK-7','CHECK-8','CHECK-9','CHECK-10','CHECK-12']
info_checks     = ['CHECK-11','CHECK-13']

labels = {
    'CHECK-1':  'INVALID TIMESTAMP',
    'CHECK-2':  'OVERLAPPING ENTRIES',
    'CHECK-3':  'TIMESHEET ON LEAVE DAY',
    'CHECK-4':  'UNASSIGNED PROJECT BILLING',
    'CHECK-5':  'ARCHIVED PROJECT BILLING',
    'CHECK-6':  'INCONSISTENT HOURLY RATE',
    'CHECK-7':  'MISSING ACTIVITY',
    'CHECK-8':  'MISSING DESCRIPTION',
    'CHECK-9':  'MISSING PROJECT',
    'CHECK-10': 'DEACTIVATED EMPLOYEE BILLING',
    'CHECK-11': 'WEEKEND ENTRIES',
    'CHECK-12': 'MISSING TIMESHEET — ACTIVE DAY',
    'CHECK-13': 'HOURS FIELD ACCURACY',
}

n_crit = sum(len(issues[c]) for c in critical_checks)
n_warn = sum(len(issues[c]) for c in warning_checks)
n_info = sum(len(issues[c]) for c in info_checks)

from datetime import date as date_cls
today = date_cls.today().isoformat()

print(f"\n=== AUDIT REPORT — kimai_timesheets.csv — {today} ===")
print(f"\nSUMMARY")
print(f"  Total entries audited : {len(ts)}")
print(f"  CRITICAL issues       : {n_crit}")
print(f"  WARNING issues        : {n_warn}")
print(f"  INFO issues           : {n_info}")

# --- Issues Table: User | Date | Issue ---
uw, dw, iw = 8, 12, 72
header = f"{'User':<{uw}}  {'Date':<{dw}}  {'Issue':<{iw}}"
sep    = "-" * len(header)

print(f"\n=== ISSUES TABLE ===")
print(header)
print(sep)

sev_label = {0: '[CRITICAL]', 1: '[WARNING] ', 2: '[INFO]    '}
# Sort: severity asc, then user, then date
for sev_ord, user, date, check, severity, brief, _ in sorted(all_issues, key=lambda x: (x[0], x[1], x[2])):
    tag   = sev_label[sev_ord]
    issue_str = f"{tag} {check}: {brief}"
    # Wrap long issue strings
    max_iw = iw
    if len(issue_str) <= max_iw:
        print(f"{user:<{uw}}  {date:<{dw}}  {issue_str}")
    else:
        print(f"{user:<{uw}}  {date:<{dw}}  {issue_str[:max_iw]}")
        remainder = issue_str[max_iw:]
        indent = " " * (uw + 2 + dw + 2)
        while remainder:
            print(f"{indent}{remainder[:max_iw]}")
            remainder = remainder[max_iw:]

print(sep)
print(f"{'':>{uw}}  {'':>{dw}}  Total: {n_crit} CRITICAL  {n_warn} WARNING  {n_info} INFO")

# --- Detailed findings by check ---
for section, checks in [('CRITICAL', critical_checks), ('WARNING', warning_checks), ('INFO', info_checks)]:
    print(f"\n--- {section} ---")
    for c in checks:
        findings = issues[c]
        print(f"\n[{c}] {labels[c]} ({len(findings)} finding{'s' if len(findings)!=1 else ''})")
        if findings:
            for (_, detail) in findings:
                print(detail)
        else:
            print("  No issues found.")

print("\n=== END AUDIT REPORT ===")

# --- Generate HTML Report ---
SEV_COLOR = {'CRITICAL': '#dc2626', 'WARNING': '#d97706', 'INFO': '#2563eb'}
SEV_BG    = {'CRITICAL': '#fef2f2', 'WARNING': '#fffbeb', 'INFO': '#eff6ff'}
SEV_BADGE = {
    'CRITICAL': 'background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700',
    'WARNING':  'background:#d97706;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700',
    'INFO':     'background:#2563eb;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700',
}

def badge(sev):
    return f'<span style="{SEV_BADGE[sev]}">{sev}</span>'

def h(s):
    return html.escape(str(s))

esc = h

rows_html = []
for sev_ord, user, date, check, severity, brief, _ in sorted(all_issues, key=lambda x: (x[0], x[1], x[2])):
    if check == 'CHECK-13':
        continue
    bg   = SEV_BG[severity]
    rows_html.append(
        f'<tr style="background:{bg}">'
        f'<td style="padding:6px 12px;white-space:nowrap">{badge(severity)}</td>'
        f'<td style="padding:6px 12px;white-space:nowrap;font-weight:600">{h(labels[check])}</td>'
        f'<td style="padding:6px 12px;white-space:nowrap">{h(user)}</td>'
        f'<td style="padding:6px 12px;white-space:nowrap">{h(date)}</td>'
        f'<td style="padding:6px 12px">{h(brief)}</td>'
        f'</tr>'
    )

def render_check_body(c, findings, sev_color):
    if c == 'CHECK-13':
        if not hours_issues:
            return '<p style="margin:4px 0;color:#6b7280;font-style:italic">No issues found.</p>'
        th_style = 'padding:8px 10px;text-align:left;font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;white-space:nowrap'
        td_style = 'padding:6px 10px;font-size:0.82rem;border-bottom:1px solid #f3f4f6'
        rows = []
        for r in sorted(hours_issues, key=lambda x: (x['user'], x['date'])):
            diff_abs = abs(r['diff'])
            diff_color = '#dc2626' if diff_abs >= 0.4 else '#d97706' if diff_abs >= 0.25 else '#6b7280'
            rows.append(
                f'<tr>'
                f'<td style="{td_style};color:#9ca3af">#{r["row"]}</td>'
                f'<td style="{td_style};font-weight:600">{esc(r["user"])}</td>'
                f'<td style="{td_style};white-space:nowrap">{esc(r["date"])}</td>'
                f'<td style="{td_style}">{esc(r["project"])}</td>'
                f'<td style="{td_style}">{esc(r["activity"])}</td>'
                f'<td style="{td_style};text-align:right">{r["declared"]}</td>'
                f'<td style="{td_style};text-align:right">{r["calc"]}</td>'
                f'<td style="{td_style};text-align:right;font-weight:700;color:{diff_color}">{r["diff"]:+.2f}</td>'
                f'</tr>'
            )
        return (
            f'<div style="overflow-x:auto">'
            f'<table style="width:100%;border-collapse:collapse;font-size:0.875rem">'
            f'<thead><tr>'
            f'<th style="{th_style}">Row</th>'
            f'<th style="{th_style}">User</th>'
            f'<th style="{th_style}">Date</th>'
            f'<th style="{th_style}">Project</th>'
            f'<th style="{th_style}">Activity</th>'
            f'<th style="{th_style};text-align:right">Declared (h)</th>'
            f'<th style="{th_style};text-align:right">Calculated (h)</th>'
            f'<th style="{th_style};text-align:right">Diff (h)</th>'
            f'</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            f'</table></div>'
        )
    if findings:
        lis = ''.join(f'<li style="margin:2px 0;font-family:monospace;font-size:0.85rem">{esc(det.strip())}</li>' for (_, det) in findings)
        return f'<ul style="margin:6px 0 0 0;padding-left:1.2em">{lis}</ul>'
    return '<p style="margin:4px 0;color:#6b7280;font-style:italic">No issues found.</p>'

detail_checks = ['CHECK-11', 'CHECK-13']
detail_items = []
for c in detail_checks:
    sev_color = SEV_COLOR['INFO']
    findings = issues[c]
    count    = len(findings)
    label    = labels[c]
    body     = render_check_body(c, findings, sev_color)
    detail_items.append(
        f'<div style="margin-bottom:16px;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden">'
        f'<div style="padding:8px 14px;background:#f9fafb;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;gap:10px">'
        f'<span style="font-weight:700;color:{sev_color}">{esc(label)}</span>'
        f'<span style="margin-left:auto;font-size:0.8rem;color:#6b7280">{count} finding{"s" if count!=1 else ""}</span>'
        f'</div>'
        f'<div style="padding:8px 14px">{body}</div>'
        f'</div>'
    )

html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Timesheet Audit — {today}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f3f4f6; color: #111827; }}
  .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 24px; margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  .subtitle {{ color: #6b7280; font-size: 0.9rem; margin-bottom: 20px; }}
  .stat-grid {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ flex: 1; min-width: 140px; border-radius: 8px; padding: 16px 20px; }}
  .stat .num {{ font-size: 2rem; font-weight: 800; }}
  .stat .lbl {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  thead tr {{ background: #f9fafb; }}
  th {{ padding: 10px 12px; text-align: left; font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em; color: #6b7280; border-bottom: 2px solid #e5e7eb; }}
  tbody tr:hover {{ filter: brightness(0.97); }}
  td {{ border-bottom: 1px solid #f3f4f6; }}
  h2 {{ font-size: 1rem; }}
</style>
</head>
<body>
<div class="card">
  <h1>Timesheet Audit Report</h1>
  <p class="subtitle">kimai_timesheets.csv &mdash; generated {today}</p>
  <div class="stat-grid">
    <div class="stat" style="background:#f0fdf4">
      <div class="num" style="color:#16a34a">{len(ts)}</div>
      <div class="lbl" style="color:#15803d">Entries Audited</div>
    </div>
    <div class="stat" style="background:#fef2f2">
      <div class="num" style="color:#dc2626">{n_crit}</div>
      <div class="lbl" style="color:#b91c1c">Critical Issues</div>
    </div>
    <div class="stat" style="background:#fffbeb">
      <div class="num" style="color:#d97706">{n_warn}</div>
      <div class="lbl" style="color:#b45309">Warnings</div>
    </div>
    <div class="stat" style="background:#eff6ff">
      <div class="num" style="color:#2563eb">{n_info}</div>
      <div class="lbl" style="color:#1d4ed8">Info</div>
    </div>
  </div>
</div>

<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">All Issues</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Severity</th><th>Check</th><th>User</th><th>Date</th><th>Issue</th>
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  </div>
</div>

<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Detailed Findings</h2>
  {''.join(detail_items)}
</div>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, f"audit_{today}.html")
with open(out_path, 'w') as f:
    f.write(html_out)

print(f"\nHTML report written to: {out_path}")
```

After printing the report, tell the user:
"Run /timesheet:propose-fixes to generate a correction plan for all CRITICAL and WARNING issues."
