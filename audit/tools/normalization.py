"""
Normalization & Linking Agent logic.

Transforms raw CSV data into unified WorkUnit records and flags data quality issues.
Each WorkUnit is a single timesheet entry enriched with HR, assignment, and project context.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
from audit.loader import load_all


QUALITY_FLAGS = {
    "missing_activity":     "No activity field",
    "missing_description":  "No description field",
    "missing_project":      "No project field",
    "invalid_timestamp":    "Timestamp cannot be parsed or hour >= 24",
    "hours_mismatch":       "Declared hours differ from calculated hours by >0.15h",
    "weekend_entry":        "Entry falls on a Saturday or Sunday",
    "public_holiday_entry": "Entry falls on a public holiday",
    "late_submission":      "Timesheet submitted more than 7 days after the work date",
}

_LATE_SUBMISSION_DAYS = 7


def build_work_units() -> dict:
    """
    Build normalized WorkUnit records from all loaded data sources.

    Returns:
        {
            "work_units":          list of WorkUnit dicts,
            "total_entries":       int,
            "data_quality_issues": list of per-flag issue dicts,
            "quality_summary":     {flag: count},
            "users":               sorted list of distinct users,
            "projects":            sorted list of distinct non-empty projects,
        }
    """
    ctx = load_all()
    ts                     = ctx["ts"]
    emp_rate               = ctx["emp_rate"]
    emp_status             = ctx["emp_status"]
    user_projs             = ctx["user_projs"]
    approved_leave         = ctx["approved_leave"]
    cal_leave_partial_days = ctx.get("cal_leave_partial_days", set())
    proj_status            = ctx["proj_status"]
    proj_end_date          = ctx.get("proj_end_date", {})
    public_holidays        = ctx.get("public_holidays", set())

    work_units: list[dict] = []
    quality_issues: list[dict] = []

    for i, row in enumerate(ts, start=2):
        user         = row.get("user", "").strip()
        date         = row.get("date", "").strip()
        begin        = row.get("begin", "").strip()
        end          = row.get("end", "").strip()
        hours_s      = row.get("hours", "").strip()
        project      = row.get("project", "").strip()
        activity     = row.get("activity", "").strip()
        desc         = row.get("description", "").strip()
        rate_s       = row.get("hourly_rate", "").strip()
        submitted_at = row.get("submitted_at", "").strip()

        flags: list[str] = []

        # Hours declared
        try:
            hours_declared = float(hours_s) if hours_s else 0.0
        except ValueError:
            hours_declared = 0.0

        # Hours calculated from begin/end
        hours_calculated = None  # type: Optional[float]
        try:
            if begin and end and "T" in begin and "T" in end:
                h_b = int(begin.split("T")[1].split(":")[0])
                h_e = int(end.split("T")[1].split(":")[0])
                if h_b >= 24 or h_e >= 24:
                    flags.append("invalid_timestamp")
                else:
                    fmt = "%Y-%m-%dT%H:%M:%S"
                    b_dt = datetime.strptime(begin, fmt)
                    e_dt = datetime.strptime(end, fmt)
                    if e_dt < b_dt:
                        e_dt += timedelta(days=1)
                    hours_calculated = round((e_dt - b_dt).total_seconds() / 3600, 2)
                    if abs(hours_declared - hours_calculated) > 0.15:
                        flags.append("hours_mismatch")
        except (ValueError, IndexError):
            flags.append("invalid_timestamp")

        # Rates
        try:
            hourly_rate = float(rate_s) if rate_s else 0.0
        except ValueError:
            hourly_rate = 0.0
        canonical_rate_s = emp_rate.get(user, "")
        try:
            canonical_rate = float(canonical_rate_s) if canonical_rate_s else 0.0
        except ValueError:
            canonical_rate = 0.0

        # Data quality flags
        if not activity:
            flags.append("missing_activity")
        if not desc:
            flags.append("missing_description")
        if not project:
            flags.append("missing_project")

        # Calendar context flags
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            if d.weekday() >= 5:
                flags.append("weekend_entry")
        except ValueError:
            pass
        if date in public_holidays:
            flags.append("public_holiday_entry")

        # Late submission: submitted_at > 7 days after work date
        if submitted_at and date:
            try:
                work_dt   = datetime.strptime(date, "%Y-%m-%d")
                # submitted_at may be a full ISO datetime or a date
                sub_str   = submitted_at[:10]
                sub_dt    = datetime.strptime(sub_str, "%Y-%m-%d")
                if (sub_dt - work_dt).days > _LATE_SUBMISSION_DAYS:
                    flags.append("late_submission")
            except ValueError:
                pass

        # Contextual lookups
        is_assigned               = bool(project and project in user_projs.get(user, set()))
        is_on_leave               = (user, date) in approved_leave
        is_partial_day_leave      = (user, date) in cal_leave_partial_days
        is_deactivated            = emp_status.get(user, "") == "deactivated"
        is_archived_proj          = proj_status.get(project, "") == "archived"
        # Billing on a project past its contractual end date
        proj_end                  = proj_end_date.get(project, "")
        is_past_project_end_date  = bool(proj_end and date > proj_end)

        unit: dict = {
            "id":                f"WU-{i}",
            "row":               i,
            "user":              user,
            "date":              date,
            "begin":             begin,
            "end":               end,
            "project":           project,
            "activity":          activity,
            "description":       desc,
            "submitted_at":      submitted_at,
            "hours_declared":    hours_declared,
            "hours_calculated":  hours_calculated,
            "hourly_rate":       hourly_rate,
            "canonical_rate":    canonical_rate,
            "is_assigned":       is_assigned,
            "is_on_leave":       is_on_leave,
            "is_partial_day_leave":      is_partial_day_leave,
            "is_past_project_end_date":  is_past_project_end_date,
            "is_weekend":        "weekend_entry" in flags,
            "is_public_holiday": "public_holiday_entry" in flags,
            "employee_status":   emp_status.get(user, "active"),
            "project_status":    proj_status.get(project, "active"),
            "is_deactivated":    is_deactivated,
            "is_archived_project": is_archived_proj,
            "data_quality_flags":  flags,
        }
        work_units.append(unit)

        for f in flags:
            quality_issues.append({
                "work_unit_id": unit["id"],
                "user":         user,
                "date":         date,
                "project":      project,
                "flag":         f,
                "description":  QUALITY_FLAGS.get(f, f),
            })

    flag_counts: dict[str, int] = defaultdict(int)
    for qi in quality_issues:
        flag_counts[qi["flag"]] += 1

    return {
        "work_units":          work_units,
        "total_entries":       len(work_units),
        "data_quality_issues": quality_issues,
        "quality_summary":     dict(flag_counts),
        "users":               sorted({wu["user"] for wu in work_units}),
        "projects":            sorted({wu["project"] for wu in work_units if wu["project"]}),
    }
