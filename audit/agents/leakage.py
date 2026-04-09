"""
Revenue Leakage Agent logic.

Detects four categories of revenue leakage:
  1. rate_mismatch       — work billed at wrong rate (under- or over-billing)
  2. unlogged_work       — Slack signals of work done with no timesheet entry
  3. cap_overage         — hours logged beyond the per-user monthly contract cap
  4. scope_creep_untagged — scope change signals in Slack with no formal change order
"""
from collections import defaultdict


def detect_revenue_leakage(
    reconciled:        dict,
    slack_signals:     dict,
    contract_model:    dict,
    proj_actual_hours: dict,
    proj_budget_hours: dict,
) -> dict:
    """
    Identify all revenue leakage signals and estimate their financial impact.

    Returns:
        {
            "findings":               list of LeakageFinding dicts,
            "total_findings":         int,
            "total_estimated_impact": float  (USD),
            "finding_type_counts":    {type: count},
            "critical_count":         int,
            "warning_count":          int,
        }
    """
    findings: list[dict] = []
    projects_model = contract_model.get("projects", {})

    billable_units     = reconciled.get("billable_units", [])
    non_billable_units = reconciled.get("non_billable_units", [])

    # ------------------------------------------------------------------ #
    # 1. Rate mismatches                                                  #
    # ------------------------------------------------------------------ #
    for wu in billable_units:
        rate      = wu.get("hourly_rate", 0.0)
        canonical = wu.get("canonical_rate", 0.0)
        if canonical > 0 and rate > 0 and abs(rate - canonical) > 0.01:
            hours     = wu.get("hours_declared", 0.0)
            diff      = canonical - rate          # positive → under-billed
            impact    = round(hours * abs(diff), 2)
            direction = "under-billed" if diff > 0 else "over-billed"
            findings.append({
                "type":             "rate_mismatch",
                "subtype":          direction,
                "user":             wu["user"],
                "date":             wu["date"],
                "project":          wu["project"],
                "description": (
                    f"{wu['user']} billed at ${rate}/hr vs canonical ${canonical}/hr "
                    f"({direction}) — {hours}h → estimated impact: ${impact:,.2f}"
                ),
                "estimated_impact": impact,
                "severity":         "CRITICAL" if impact > 100 else "WARNING",
                "work_unit_id":     wu["id"],
            })

    # ------------------------------------------------------------------ #
    # 2. Unlogged work (Slack evidence)                                   #
    # ------------------------------------------------------------------ #
    for sig in slack_signals.get("work_without_timesheet", []):
        findings.append({
            "type":             "unlogged_work",
            "subtype":          "slack_evidence",
            "user":             sig["user"],
            "date":             sig["date"],
            "project":          None,
            "description": (
                f"{sig['user']} mentioned work on {sig['date']} in "
                f"#{sig.get('channel', 'Slack')} but has no timesheet entry. "
                f"Message: \"{sig['text'][:120]}\""
            ),
            "estimated_impact": None,
            "severity":         "WARNING",
        })

    # ------------------------------------------------------------------ #
    # 3. Per-user monthly cap overages                                    #
    # ------------------------------------------------------------------ #
    # Aggregate billable hours per (user, project, month)
    user_proj_month: dict = defaultdict(float)
    for wu in billable_units:
        month = wu["date"][:7] if len(wu.get("date", "")) >= 7 else "unknown"
        user_proj_month[(wu["user"], wu["project"], month)] += wu.get("hours_declared", 0.0)

    for (user, project, month), total_h in user_proj_month.items():
        for pname, pdata in projects_model.items():
            if pname.lower() not in project.lower() and project.lower() not in pname.lower():
                continue
            team_map = pdata.get("team_map", {})
            member = next(
                (m for k, m in team_map.items()
                 if k in user.lower() or user.lower() in k),
                None,
            )
            if member:
                cap  = member.get("monthly_hours", 0)
                rate = member.get("rate", 0.0)
                if cap > 0 and total_h > cap:
                    overage = round(total_h - cap, 2)
                    impact  = round(overage * rate, 2)
                    findings.append({
                        "type":    "cap_overage",
                        "subtype": "monthly_hours_cap",
                        "user":    user,
                        "date":    f"{month}-01",
                        "project": project,
                        "description": (
                            f"{user} logged {total_h:.1f}h on '{project}' in {month} "
                            f"vs contract cap of {cap}h — {overage:.1f}h extra, "
                            f"likely non-billable without pre-approval "
                            f"(estimated risk: ${impact:,.2f})"
                        ),
                        "estimated_impact": impact,
                        "severity":         "CRITICAL",
                    })
            break   # matched project — move on

    # ------------------------------------------------------------------ #
    # 4. Scope creep signals in Slack without formal change order         #
    # ------------------------------------------------------------------ #
    scope_signals = [
        s for s in slack_signals.get("signals", [])
        if "scope_change" in s.get("signal_types", [])
    ]
    for sig in scope_signals:
        findings.append({
            "type":    "scope_creep_untagged",
            "subtype": "slack_scope_change",
            "user":    sig["user"],
            "date":    sig["date"],
            "project": None,
            "description": (
                f"Potential informal scope extension mentioned by {sig['user']} on "
                f"{sig['date']} in #{sig.get('channel', 'Slack')}: "
                f"\"{sig['text'][:120]}\" — verify if a change order exists."
            ),
            "estimated_impact": None,
            "severity":         "INFO",
        })

    # ------------------------------------------------------------------ #
    # 5. Non-billable hours on assigned projects (recoverable revenue)    #
    # ------------------------------------------------------------------ #
    for wu in non_billable_units:
        if (
            wu.get("is_assigned")
            and not wu.get("is_on_leave")
            and not wu.get("is_deactivated")
            and wu.get("is_archived_project")
        ):
            impact = round(wu["hours_declared"] * (wu.get("hourly_rate") or wu.get("canonical_rate", 0.0)), 2)
            findings.append({
                "type":    "archived_project_hours",
                "subtype": "potential_re-tag",
                "user":    wu["user"],
                "date":    wu["date"],
                "project": wu["project"],
                "description": (
                    f"{wu['user']} logged {wu['hours_declared']}h on archived project "
                    f"'{wu['project']}' — consider re-tagging to an active project "
                    f"to recover billing (estimated: ${impact:,.2f})"
                ),
                "estimated_impact": impact,
                "severity": "WARNING",
            })

    # ---- Summarise ----
    total_impact = round(sum(f["estimated_impact"] or 0 for f in findings), 2)
    type_counts: dict[str, int] = defaultdict(int)
    for f in findings:
        type_counts[f["type"]] += 1

    return {
        "findings":               findings,
        "total_findings":         len(findings),
        "total_estimated_impact": total_impact,
        "finding_type_counts":    dict(type_counts),
        "critical_count":         sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warning_count":          sum(1 for f in findings if f["severity"] == "WARNING"),
    }
