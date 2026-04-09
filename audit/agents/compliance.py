"""
Compliance & Risk Agent logic.

Checks contract adherence across six risk categories:
  1. unauthorized_overtime         — >8h/day without written approval
  2. leave_day_billing             — timesheet entry on an approved leave day
  3. public_holiday_billing        — billing on a public holiday without approval
  4. deactivated_employee_billing  — deactivated user has timesheet entries
  5. archived_project_billing      — billing to an archived/closed project
  6. unassigned_project_billing    — resource not assigned but billing to project
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


def run_compliance_checks(
    reconciled:     dict,
    contract_model: dict,
) -> dict:
    """
    Run all compliance checks and return structured findings.

    Returns:
        {
            "findings":           list of ComplianceFinding dicts,
            "total_findings":     int,
            "finding_type_counts": {type: count},
            "critical_count":     int,
            "warning_count":      int,
        }
    """
    global_rules   = contract_model.get("global_rules", {})
    requires_ot_ap = global_rules.get("overtime_requires_approval", False)

    all_units: list[dict] = reconciled.get("work_units", [])
    findings:  list[dict] = []

    # ------------------------------------------------------------------ #
    # 1. Unauthorized overtime (>8h in a day)                            #
    # ------------------------------------------------------------------ #
    user_date_hours: dict = defaultdict(float)
    user_date_projs: dict = defaultdict(list)
    for wu in all_units:
        key = (wu["user"], wu["date"])
        user_date_hours[key] += wu.get("hours_declared", 0.0)
        user_date_projs[key].append(wu.get("project", ""))

    if requires_ot_ap:
        for (user, date), total_h in user_date_hours.items():
            if total_h > 8.0:
                projs = ", ".join(set(filter(None, user_date_projs[(user, date)])))
                findings.append({
                    "type":            "unauthorized_overtime",
                    "user":            user,
                    "date":            date,
                    "project":         projs,
                    "description": (
                        f"{user} logged {total_h:.1f}h on {date} — exceeds 8h threshold. "
                        f"Contract requires written approval for overtime (no record found)."
                    ),
                    "contract_clause": "overtime_requires_approval",
                    "severity":        "WARNING",
                })

    # ------------------------------------------------------------------ #
    # 2–6. Per-row checks                                                 #
    # ------------------------------------------------------------------ #
    seen: set = set()

    def _add(type_: str, wu: dict, description: str, clause: Optional[str], sev: str) -> None:
        key = (type_, wu["user"], wu["date"], wu.get("project", ""))
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "type":            type_,
            "user":            wu["user"],
            "date":            wu["date"],
            "project":         wu.get("project", ""),
            "description":     description,
            "contract_clause": clause,
            "severity":        sev,
        })

    for wu in all_units:
        if wu.get("is_on_leave"):
            _add(
                "leave_day_billing", wu,
                f"{wu['user']} billed {wu['hours_declared']}h on approved leave day "
                f"{wu['date']} — project: {wu['project']}",
                "leave_policy", "CRITICAL",
            )

        if wu.get("is_public_holiday"):
            _add(
                "public_holiday_billing", wu,
                f"{wu['user']} billed {wu['hours_declared']}h on public holiday "
                f"{wu['date']} — verify client pre-approved holiday billing",
                "public_holidays_policy", "WARNING",
            )

        if wu.get("is_deactivated"):
            _add(
                "deactivated_employee_billing", wu,
                f"Deactivated employee {wu['user']} has timesheet entries on "
                f"{wu['date']} for project '{wu['project']}'",
                None, "CRITICAL",
            )

        if wu.get("is_archived_project"):
            _add(
                "archived_project_billing", wu,
                f"{wu['user']} billed {wu['hours_declared']}h to archived project "
                f"'{wu['project']}' on {wu['date']}",
                None, "CRITICAL",
            )

        if not wu.get("is_assigned") and wu.get("project"):
            _add(
                "unassigned_project_billing", wu,
                f"{wu['user']} billed to '{wu['project']}' but is not assigned to "
                f"it in the HR system — may cause invoice dispute",
                None, "CRITICAL",
            )

    # ---- Summarise ----
    type_counts: dict[str, int] = defaultdict(int)
    for f in findings:
        type_counts[f["type"]] += 1

    return {
        "findings":            findings,
        "total_findings":      len(findings),
        "finding_type_counts": dict(type_counts),
        "critical_count":      sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warning_count":       sum(1 for f in findings if f["severity"] == "WARNING"),
    }
