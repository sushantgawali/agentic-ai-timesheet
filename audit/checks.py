"""
All 13 audit checks.

Each check returns a list of issue dicts:
  {
    "severity":    "CRITICAL" | "WARNING" | "INFO",
    "check":       "CHECK-N",
    "user":        str,
    "date":        str,
    "brief":       str,   # short one-liner for the issues table
    "detail":      str,   # full detail for the detailed section
  }

CHECK-13 also populates the hours_issues list (returned separately via run_all()).
"""
from collections import defaultdict
from datetime import datetime, timedelta
from audit.loader import load_all

LABELS = {
    "CHECK-1":  "INVALID TIMESTAMP",
    "CHECK-2":  "OVERLAPPING ENTRIES",
    "CHECK-3":  "TIMESHEET ON LEAVE DAY",
    "CHECK-4":  "UNASSIGNED PROJECT BILLING",
    "CHECK-5":  "ARCHIVED PROJECT BILLING",
    "CHECK-6":  "INCONSISTENT HOURLY RATE",
    "CHECK-7":  "MISSING ACTIVITY",
    "CHECK-8":  "MISSING DESCRIPTION",
    "CHECK-9":  "MISSING PROJECT",
    "CHECK-10": "DEACTIVATED EMPLOYEE BILLING",
    "CHECK-11": "WEEKEND ENTRIES",
    "CHECK-12": "MISSING TIMESHEET — ACTIVE DAY",
    "CHECK-13": "HOURS FIELD ACCURACY",
}

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _issue(check, severity, user, date, brief, detail):
    return {
        "severity": severity,
        "check": check,
        "label": LABELS[check],
        "user": user,
        "date": date,
        "brief": brief,
        "detail": detail,
    }


def run_all() -> tuple[list[dict], list[dict]]:
    """
    Run all 13 checks and return (issues, hours_issues).

    issues       — list of issue dicts (all checks)
    hours_issues — list of row-level hour-accuracy records (CHECK-13 only)
    """
    ctx = load_all()
    ts            = ctx["ts"]
    emp_rate      = ctx["emp_rate"]
    emp_status    = ctx["emp_status"]
    user_projs    = ctx["user_projs"]
    approved_leave= ctx["approved_leave"]
    proj_status   = ctx["proj_status"]
    slack_active  = ctx["slack_active"]
    git_active    = ctx["git_active"]

    issues: list[dict] = []
    hours_issues: list[dict] = []

    # --- Per-row checks (CHECK-1, 3–11, 13) ---
    for i, row in enumerate(ts, start=2):
        user     = row.get("user", "").strip()
        date     = row.get("date", "").strip()
        begin    = row.get("begin", "").strip()
        end      = row.get("end", "").strip()
        hours    = row.get("hours", "").strip()
        project  = row.get("project", "").strip()
        activity = row.get("activity", "").strip()
        desc     = row.get("description", "").strip()
        rate     = row.get("hourly_rate", "").strip()

        # CHECK-1: Invalid or unparseable timestamp
        for field_name, val in [("begin", begin), ("end", end)]:
            if "T" in val:
                time_part = val.split("T")[1]
                try:
                    h = int(time_part.split(":")[0])
                    if h >= 24:
                        issues.append(_issue(
                            "CHECK-1", "CRITICAL", user, date,
                            f"Invalid timestamp: {field_name}={val}",
                            f"Row {i}: {user} | {date} | {field_name}={val}",
                        ))
                except (ValueError, IndexError):
                    issues.append(_issue(
                        "CHECK-1", "CRITICAL", user, date,
                        f"Unparseable timestamp: {field_name}={val}",
                        f"Row {i}: {user} | {date} | {field_name}={val} (unparseable)",
                    ))

        # CHECK-3: Billed on approved leave day
        if (user, date) in approved_leave:
            issues.append(_issue(
                "CHECK-3", "CRITICAL", user, date,
                f"Billed on approved leave day — project={project}",
                f"Row {i}: {user} | {date} | project={project}",
            ))

        # CHECK-4: Unassigned project
        if project and project not in user_projs.get(user, set()):
            issues.append(_issue(
                "CHECK-4", "CRITICAL", user, date,
                f"Unassigned project: '{project}'",
                f"Row {i}: {user} billed {project!r} | assigned={sorted(user_projs.get(user, set()))}",
            ))

        # CHECK-5: Archived project
        if project and proj_status.get(project, "") == "archived":
            issues.append(_issue(
                "CHECK-5", "CRITICAL", user, date,
                f"Archived project: '{project}'",
                f"Row {i}: {user} | {date} | project={project} (archived)",
            ))

        # CHECK-6: Wrong hourly rate
        canonical = emp_rate.get(user, "")
        if canonical and rate and rate != canonical:
            issues.append(_issue(
                "CHECK-6", "WARNING", user, date,
                f"Wrong rate: {rate} (canonical={canonical})",
                f"Row {i}: {user} | rate={rate} | canonical={canonical}",
            ))

        # CHECK-7: Missing activity
        if not activity:
            issues.append(_issue(
                "CHECK-7", "WARNING", user, date,
                f"Missing activity — desc={desc[:35]!r}",
                f"Row {i}: {user} | {date} | project={project} | desc={desc[:40]!r}",
            ))

        # CHECK-8: Missing description
        if not desc:
            issues.append(_issue(
                "CHECK-8", "WARNING", user, date,
                f"Missing description — activity={activity or '(none)'}",
                f"Row {i}: {user} | {date} | project={project} | activity={activity}",
            ))

        # CHECK-9: Missing project
        if not project:
            issues.append(_issue(
                "CHECK-9", "WARNING", user, date,
                f"Missing project — activity={activity}",
                f"Row {i}: {user} | {date} | activity={activity}",
            ))

        # CHECK-10: Deactivated employee
        if emp_status.get(user, "") == "deactivated":
            issues.append(_issue(
                "CHECK-10", "WARNING", user, date,
                f"Deactivated employee billing — project={project}",
                f"Row {i}: {user} | {date} | project={project}",
            ))

        # CHECK-11: Weekend entry
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            if d.weekday() >= 5:
                issues.append(_issue(
                    "CHECK-11", "INFO", user, date,
                    f"Weekend entry ({d.strftime('%A')}) — project={project}",
                    f"Row {i}: {user} | {date} ({d.strftime('%A')}) | project={project} | desc={desc[:40]!r}",
                ))
        except ValueError:
            pass

        # CHECK-13: Hours accuracy
        skip = any(
            "T" in v and int(v.split("T")[1].split(":")[0]) >= 24
            for v in [begin, end] if "T" in v
        )
        if not skip and begin and end and hours:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S"
                b_dt = datetime.strptime(begin, fmt)
                e_dt = datetime.strptime(end, fmt)
                if e_dt < b_dt:
                    e_dt += timedelta(days=1)
                calc     = round((e_dt - b_dt).total_seconds() / 3600, 2)
                declared = round(float(hours), 2)
                if abs(declared - calc) > 0.15:
                    diff = round(declared - calc, 2)
                    issues.append(_issue(
                        "CHECK-13", "INFO", user, date,
                        f"Hours mismatch: declared={declared}h vs calc={calc}h (diff={diff:+.2f}h)",
                        f"Row {i}: {user} | {date} | declared={declared}h calculated={calc}h diff={diff:+.2f}h",
                    ))
                    hours_issues.append({
                        "row": i, "user": user, "date": date,
                        "project": project, "activity": activity,
                        "declared": declared, "calc": calc, "diff": diff,
                    })
            except (ValueError, TypeError):
                pass

    # --- CHECK-2: Overlapping entries ---
    by_user_date: dict = defaultdict(list)
    for i, row in enumerate(ts, start=2):
        user  = row.get("user", "").strip()
        date  = row.get("date", "").strip()
        begin = row.get("begin", "").strip()
        end   = row.get("end", "").strip()
        if begin and end and "T" in begin and "T" in end:
            try:
                if int(begin.split("T")[1].split(":")[0]) >= 24:
                    continue
                if int(end.split("T")[1].split(":")[0]) >= 24:
                    continue
                fmt = "%Y-%m-%dT%H:%M:%S"
                b_dt = datetime.strptime(begin, fmt)
                e_dt = datetime.strptime(end, fmt)
                by_user_date[(user, date)].append(
                    (i, b_dt, e_dt, row.get("project", ""), row.get("activity", ""))
                )
            except ValueError:
                pass

    for (user, date), entries in by_user_date.items():
        entries.sort(key=lambda x: x[1])
        seen: set = set()
        for j in range(len(entries)):
            for k in range(j + 1, len(entries)):
                ri, rb, re, rp, _ = entries[j]
                si, sb, se, sp, _ = entries[k]
                if rb < se and sb < re and re != sb:
                    key = (min(ri, si), max(ri, si))
                    if key in seen:
                        continue
                    seen.add(key)
                    overlap_min = round((min(re, se) - max(rb, sb)).total_seconds() / 60)
                    brief  = (
                        f"Overlap {overlap_min}min — "
                        f"row{ri}=[{rb.strftime('%H:%M')}-{re.strftime('%H:%M')} {rp}] "
                        f"vs row{si}=[{sb.strftime('%H:%M')}-{se.strftime('%H:%M')} {sp}]"
                    )
                    detail = (
                        f"Rows {ri}&{si}: {user} | {date} | overlap={overlap_min}min | "
                        f"row{ri}=[{rb.strftime('%H:%M')}-{re.strftime('%H:%M')} {rp}] "
                        f"row{si}=[{sb.strftime('%H:%M')}-{se.strftime('%H:%M')} {sp}]"
                    )
                    issues.append(_issue("CHECK-2", "CRITICAL", user, date, brief, detail))

    # --- CHECK-12: Active on Slack or Git but no timesheet ---
    ts_days = {(r["user"], r["date"]) for r in ts}
    active_days = set(slack_active.keys()) | git_active
    for user, date in sorted(active_days):
        if (user, date) not in ts_days and (user, date) not in approved_leave:
            signals = []
            if (user, date) in slack_active:
                signals.append(f"{slack_active[(user, date)]} Slack msgs")
            if (user, date) in git_active:
                signals.append("git commits")
            signal_str = ", ".join(signals)
            issues.append(_issue(
                "CHECK-12", "WARNING", user, date,
                f"Active ({signal_str}) but no timesheet",
                f"{user} | {date} | {signal_str}",
            ))

    # Sort: severity, then user, then date
    issues.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["user"], x["date"]))
    return issues, hours_issues
