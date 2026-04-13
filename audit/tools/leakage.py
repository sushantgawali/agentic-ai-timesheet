"""
Revenue Leakage Agent logic.

Detects five categories of revenue leakage:
  1. rate_mismatch              — work billed at wrong rate (under- or over-billing)
  2. unlogged_work              — Slack signals of work done with no timesheet entry
  3. cap_overage                — hours logged beyond the per-user monthly contract cap
  4. scope_creep_untagged       — scope change signals in Slack with no formal change order
  5. contract_hours_underbilling — employee billed significantly fewer hours than their HR contract
"""
from collections import defaultdict


def detect_revenue_leakage(
    reconciled:        dict,
    slack_signals:     dict,
    contract_model:    dict,
    proj_actual_hours: dict,
    proj_budget_hours: dict,
    loader_context:    dict = None,
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
    # Build (user_lower, project_lower) → (sow_rate, sow_project_name)   #
    # lookup so rate mismatch can prefer the SOW-agreed rate over the     #
    # HR canonical rate.                                                  #
    # ------------------------------------------------------------------ #
    sow_rate_lookup: dict[tuple[str, str], tuple[float, str]] = {}
    for pname, pdata in projects_model.items():
        for key, member in pdata.get("team_map", {}).items():
            sow_rate = member.get("rate", 0.0) or 0.0
            if sow_rate > 0:
                sow_rate_lookup[(key.lower(), pname.lower())] = (sow_rate, pname)

    def _sow_rate_for(user: str, project: str) -> tuple[float, str]:
        """Return (sow_rate, sow_project_name) or (0.0, '') if not found."""
        u = user.lower()
        p = project.lower()
        # Prefer a match on both user and project
        for (k, pn), (r, full_pname) in sow_rate_lookup.items():
            if (k in u or u in k) and (pn in p or p in pn):
                return r, full_pname
        # Fall back to user-only match (rate applies across projects)
        for (k, _pn), (r, full_pname) in sow_rate_lookup.items():
            if k in u or u in k:
                return r, full_pname
        return 0.0, ""

    # ------------------------------------------------------------------ #
    # 1. Rate mismatches                                                  #
    # ------------------------------------------------------------------ #
    for wu in billable_units:
        rate      = wu.get("hourly_rate", 0.0)
        canonical = wu.get("canonical_rate", 0.0)
        sow_r, sow_proj = _sow_rate_for(wu["user"], wu["project"])

        # Priority: SOW rate → HR canonical rate
        if sow_r > 0:
            expected_rate   = sow_r
            expected_source = f"SOW ({sow_proj})"
        elif canonical > 0:
            expected_rate   = canonical
            expected_source = "HR canonical"
        else:
            continue  # no reference rate — nothing to compare against

        if rate <= 0 or abs(rate - expected_rate) <= 0.01:
            continue

        hours     = wu.get("hours_declared", 0.0)
        diff      = expected_rate - rate          # positive → under-billed
        impact    = round(hours * abs(diff), 2)
        direction = "under-billed" if diff > 0 else "over-billed"
        findings.append({
            "type":             "rate_mismatch",
            "subtype":          direction,
            "user":             wu["user"],
            "date":             wu["date"],
            "project":          wu["project"],
            "description": (
                f"{wu['user']} billed at ${rate}/hr vs {expected_source} rate "
                f"${expected_rate}/hr ({direction}) — {hours}h → "
                f"estimated impact: ${impact:,.2f}"
            ),
            "estimated_impact": impact,
            "severity":         "CRITICAL" if impact > 100 else "WARNING",
            "work_unit_id":     wu["id"],
            "rate_source":      expected_source,
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

    # ------------------------------------------------------------------ #
    # 6. Contract hours underbilling                                      #
    # Employees with a contract_hrs commitment who billed materially      #
    # fewer hours in a month than their contract specifies.               #
    # ------------------------------------------------------------------ #
    if loader_context is None:
        try:
            from audit.loader import load_all as _load_all
            loader_context = _load_all()
        except Exception:
            loader_context = {}
    emp_contract_hrs: dict = loader_context.get("emp_contract_hrs", {})

    if emp_contract_hrs:
        # Aggregate billable hours per (user, month)
        user_month_hours: dict = defaultdict(float)
        for wu in billable_units:
            month = wu["date"][:7] if len(wu.get("date", "")) >= 7 else "unknown"
            user_month_hours[(wu["user"], month)] += wu.get("hours_declared", 0.0)

        # contract_hrs represents the standard daily hours (e.g. 8h/day).
        # Monthly expectation = daily_hrs × 22 working days (avg).
        _WORKING_DAYS_PER_MONTH = 22
        _UNDERBILL_THRESHOLD = 0.70  # flag if actual < 70% of expected

        for (user, month), billed_h in user_month_hours.items():
            contract_daily = emp_contract_hrs.get(user, 0.0)
            if contract_daily <= 0:
                continue
            expected_monthly = round(contract_daily * _WORKING_DAYS_PER_MONTH, 1)
            if billed_h >= expected_monthly * _UNDERBILL_THRESHOLD:
                continue
            shortfall = round(expected_monthly - billed_h, 1)
            # Use canonical rate for impact estimate
            rate = 0.0
            for wu in billable_units:
                if wu["user"] == user:
                    rate = wu.get("canonical_rate") or wu.get("hourly_rate") or 0.0
                    if rate:
                        break
            impact = round(shortfall * rate, 2) if rate else None
            findings.append({
                "type":    "contract_hours_underbilling",
                "subtype": "hours_below_contract",
                "user":    user,
                "date":    f"{month}-01",
                "project": None,
                "description": (
                    f"{user} billed {billed_h:.1f}h in {month} vs contract expectation of "
                    f"{expected_monthly:.1f}h/month ({contract_daily}h/day × {_WORKING_DAYS_PER_MONTH} days) — "
                    f"{shortfall:.1f}h shortfall"
                    + (f", estimated impact: ${impact:,.2f}" if impact else "")
                ),
                "estimated_impact": impact,
                "severity":         "WARNING",
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
