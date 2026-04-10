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
    "CHECK-14": "BILLING ON PUBLIC HOLIDAY",
    "CHECK-15": "PROJECT BUDGET OVERRUN",
    "CHECK-16": "NAME AMBIGUITY / VARIANT",
    "CHECK-17": "CLIENT HOLIDAY BILLING",
    "CHECK-18": "LOW HOURS — ESCALATION",
}

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _issue(check, severity, user, date, brief, detail, project=""):
    return {
        "severity": severity,
        "check": check,
        "label": LABELS[check],
        "user": user,
        "date": date,
        "brief": brief,
        "detail": detail,
        "project": project,
    }


def run_all() -> tuple[list[dict], list[dict]]:
    """
    Run all 13 checks and return (issues, hours_issues).

    issues       — list of issue dicts (all checks)
    hours_issues — list of row-level hour-accuracy records (CHECK-13 only)
    """
    ctx = load_all()
    ts             = ctx["ts"]
    emp_rate       = ctx["emp_rate"]
    emp_status     = ctx["emp_status"]
    user_projs     = ctx["user_projs"]
    approved_leave = ctx["approved_leave"]
    proj_status    = ctx["proj_status"]
    slack_active   = ctx["slack_active"]
    git_active     = ctx["git_active"]
    public_holidays = ctx.get("public_holidays", set())

    # Email-derived signals
    email_signals        = ctx.get("email_signals", {})
    extra_time_approvals = email_signals.get("extra_time_approvals", set())
    extended_end_dates   = email_signals.get("extended_end_dates", {})
    client_holiday_dates = email_signals.get("client_holiday_dates", set())
    escalations          = email_signals.get("escalations", [])
    email_assignments    = email_signals.get("email_assignments", set())

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
                            project=project,
                        ))
                except (ValueError, IndexError):
                    issues.append(_issue(
                        "CHECK-1", "CRITICAL", user, date,
                        f"Unparseable timestamp: {field_name}={val}",
                        f"Row {i}: {user} | {date} | {field_name}={val} (unparseable)",
                        project=project,
                    ))

        # CHECK-3: Billed on approved leave day
        if (user, date) in approved_leave:
            issues.append(_issue(
                "CHECK-3", "CRITICAL", user, date,
                f"Billed on approved leave day — project={project}",
                f"Row {i}: {user} | {date} | project={project}",
                project=project,
            ))

        # CHECK-4: Unassigned project
        # Exempt if an onboarding email confirms this (user, project) assignment
        email_assigned = any(
            user.lower() in u and project.lower() in p
            for u, p in email_assignments
        )
        if project and project not in user_projs.get(user, set()) and not email_assigned:
            issues.append(_issue(
                "CHECK-4", "CRITICAL", user, date,
                f"Unassigned project: '{project}'",
                f"Row {i}: {user} billed {project!r} | assigned={sorted(user_projs.get(user, set()))}",
                project=project,
            ))

        # CHECK-5: Archived project
        # Exempt if a date_extension email has pushed the project's end date beyond this billing date
        proj_extended = any(
            proj_key in project.lower() or project.lower() in proj_key
            for proj_key, new_end in extended_end_dates.items()
            if date <= new_end
        )
        if project and proj_status.get(project, "") == "archived" and not proj_extended:
            issues.append(_issue(
                "CHECK-5", "CRITICAL", user, date,
                f"Archived project: '{project}'",
                f"Row {i}: {user} | {date} | project={project} (archived)",
                project=project,
            ))

        # CHECK-6: Wrong hourly rate
        canonical = emp_rate.get(user, "")
        if canonical and rate and rate != canonical:
            issues.append(_issue(
                "CHECK-6", "WARNING", user, date,
                f"Wrong rate: {rate} (canonical={canonical})",
                f"Row {i}: {user} | rate={rate} | canonical={canonical}",
                project=project,
            ))

        # CHECK-7: Missing activity
        if not activity:
            issues.append(_issue(
                "CHECK-7", "WARNING", user, date,
                f"Missing activity — desc={desc[:35]!r}",
                f"Row {i}: {user} | {date} | project={project} | desc={desc[:40]!r}",
                project=project,
            ))

        # CHECK-8: Missing description
        if not desc:
            issues.append(_issue(
                "CHECK-8", "WARNING", user, date,
                f"Missing description — activity={activity or '(none)'}",
                f"Row {i}: {user} | {date} | project={project} | activity={activity}",
                project=project,
            ))

        # CHECK-9: Missing project — project field is intentionally empty
        if not project:
            issues.append(_issue(
                "CHECK-9", "WARNING", user, date,
                f"Missing project — activity={activity}",
                f"Row {i}: {user} | {date} | activity={activity}",
            ))

        # CHECK-10: Deactivated employee
        if emp_status.get(user, "") == "deactivated":
            issues.append(_issue(
                "CHECK-10", "CRITICAL", user, date,
                f"Deactivated employee billing — project={project}",
                f"Row {i}: {user} | {date} | project={project}",
                project=project,
            ))

        # CHECK-11: Weekend entry
        # Exempt if extra_time approval email exists for this (user, date)
        extra_time_approved = (user.lower(), date) in extra_time_approvals
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            if d.weekday() >= 5 and not extra_time_approved:
                issues.append(_issue(
                    "CHECK-11", "INFO", user, date,
                    f"Weekend entry ({d.strftime('%A')}) — project={project}",
                    f"Row {i}: {user} | {date} ({d.strftime('%A')}) | project={project} | desc={desc[:40]!r}",
                    project=project,
                ))
        except ValueError:
            pass

        # CHECK-14: Billing on a public holiday (only runs when holiday data is available)
        # Exempt if extra_time approval exists for this (user, date)
        if public_holidays and date in public_holidays and not extra_time_approved:
            issues.append(_issue(
                "CHECK-14", "WARNING", user, date,
                f"Billed on public holiday — project={project}",
                f"Row {i}: {user} | {date} (public holiday) | project={project}",
                project=project,
            ))

        # CHECK-17: Billing on a client-declared no-billing holiday
        if client_holiday_dates and date in client_holiday_dates and not extra_time_approved:
            issues.append(_issue(
                "CHECK-17", "WARNING", user, date,
                f"Billed on client holiday — project={project}",
                f"Row {i}: {user} | {date} (client holiday) | project={project} | "
                f"client declared no-billing day",
                project=project,
            ))

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
                        project=project,
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
                    issues.append(_issue("CHECK-2", "CRITICAL", user, date, brief, detail, project=rp))

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

    # --- CHECK-15: Project budget overrun (project-level, not per-row) ---
    proj_budget_hours = ctx.get("proj_budget_hours", {})
    proj_budget_cost  = ctx.get("proj_budget_cost",  {})
    proj_actual_hours = ctx.get("proj_actual_hours", {})
    proj_actual_cost  = ctx.get("proj_actual_cost",  {})

    for project, budget_h in proj_budget_hours.items():
        if budget_h <= 0:
            continue
        actual_h = proj_actual_hours.get(project, 0.0)
        actual_c = proj_actual_cost.get(project, 0.0)
        budget_c = proj_budget_cost.get(project, 0.0)
        pct      = actual_h / budget_h
        h_diff   = actual_h - budget_h
        c_diff   = actual_c - budget_c

        if pct > 1.0:
            issues.append(_issue(
                "CHECK-15", "CRITICAL", "", project,
                f"Over budget: {actual_h:.1f}h logged vs {budget_h:.0f}h budget ({pct:.0%}) — cost ${actual_c:,.0f} vs ${budget_c:,.0f}",
                f"Project={project} | hours: actual={actual_h:.1f} budget={budget_h:.0f} diff={h_diff:+.1f} | cost: actual=${actual_c:,.0f} budget=${budget_c:,.0f} diff=${c_diff:+,.0f}",
                project=project,
            ))
        elif pct > 0.9:
            issues.append(_issue(
                "CHECK-15", "WARNING", "", project,
                f"Near budget limit: {actual_h:.1f}h logged vs {budget_h:.0f}h budget ({pct:.0%}) — cost ${actual_c:,.0f} vs ${budget_c:,.0f}",
                f"Project={project} | hours: actual={actual_h:.1f} budget={budget_h:.0f} diff={h_diff:+.1f} | cost: actual=${actual_c:,.0f} budget=${budget_c:,.0f} diff=${c_diff:+,.0f}",
                project=project,
            ))

    # --- CHECK-18: Low hours — escalation emails ---
    for esc in escalations:
        issues.append(_issue(
            "CHECK-18", "WARNING",
            esc["user"], esc["date"],
            f"Low hours escalation on {esc['project']}: "
            f"expected {esc['expected_hrs']:.0f}h, logged {esc['actual_hrs']:.0f}h",
            f"{esc['user']} | {esc['date']} | project={esc['project']} | "
            f"expected={esc['expected_hrs']:.0f}h actual={esc['actual_hrs']:.0f}h | "
            f"raised by escalation email — missing {esc['expected_hrs'] - esc['actual_hrs']:.0f}h",
            project=esc["project"],
        ))

    # --- CHECK-16: Name ambiguity / variant detection ---
    all_users    = sorted({r["user"] for r in ts if r.get("user")})
    all_projects = sorted({r["project"] for r in ts if r.get("project")})

    # (a) Users sharing the same first-name token → ambiguous references in Slack/SOW
    first_name_map: dict = defaultdict(list)
    for u in all_users:
        first = u.split(".")[0].split("_")[0].split(" ")[0].lower()
        first_name_map[first].append(u)
    for first, group in sorted(first_name_map.items()):
        if len(group) > 1:
            issues.append(_issue(
                "CHECK-16", "WARNING", ", ".join(group), "",
                f"Ambiguous first name '{first}': {len(group)} users share it",
                f"Users: {', '.join(group)} — references to '{first}' in Slack/SOW/email "
                f"are unresolvable without full names. Standardise identifiers.",
            ))

    # (b) Users where one name is a prefix/substring of another → likely variant of same person
    for i, u1 in enumerate(all_users):
        for u2 in all_users[i + 1:]:
            u1l, u2l = u1.lower(), u2.lower()
            # substring match only when the shorter name has no dot (bare first name)
            if "." not in u1l and u1l in u2l:
                issues.append(_issue(
                    "CHECK-16", "WARNING", f"{u1} / {u2}", "",
                    f"Name variant risk: '{u1}' may be incomplete form of '{u2}'",
                    f"'{u1}' (no surname) appears alongside '{u2}' — could be same person "
                    f"with inconsistent naming, causing double-counting or missed matches.",
                ))
            elif "." not in u2l and u2l in u1l:
                issues.append(_issue(
                    "CHECK-16", "WARNING", f"{u1} / {u2}", "",
                    f"Name variant risk: '{u2}' may be incomplete form of '{u1}'",
                    f"'{u2}' (no surname) appears alongside '{u1}' — could be same person "
                    f"with inconsistent naming, causing double-counting or missed matches.",
                ))

    # (c) Project name variants — same words, different casing or spacing
    proj_norm_map: dict = defaultdict(list)
    for p in all_projects:
        norm = p.lower().replace("-", " ").replace("_", " ").strip()
        proj_norm_map[norm].append(p)
    for norm, group in sorted(proj_norm_map.items()):
        if len(group) > 1:
            issues.append(_issue(
                "CHECK-16", "WARNING", "", ", ".join(group),
                f"Project name variant: {len(group)} spellings for '{norm}'",
                f"Project spellings: {', '.join(group)} — may split hours across "
                f"duplicate project buckets. Normalise to a single canonical name.",
            ))

    # Sort: severity, then user, then date
    issues.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["user"], x["date"]))
    return issues, hours_issues
