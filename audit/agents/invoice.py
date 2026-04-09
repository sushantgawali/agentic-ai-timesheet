"""
Invoice Drafting Agent logic.

Aggregates billable work units into invoice line items, applying contract rates
where available and falling back to timesheet rates.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional, Tuple


def _contract_rate_and_role(
    user: str, project: str, projects_model: dict
) -> Tuple[Optional[float], str]:
    """Look up the contract rate and role for a user on a project."""
    u_lc = user.lower()
    for pname, pdata in projects_model.items():
        if pname.lower() not in project.lower() and project.lower() not in pname.lower():
            continue
        for k, member in pdata.get("team_map", {}).items():
            if k in u_lc or u_lc in k:
                return float(member.get("rate", 0) or 0), member.get("role", "")
        break   # matched project but user not in team
    return None, ""


def build_invoice_draft(
    reconciled:     dict,
    contract_model: dict,
) -> dict:
    """
    Build invoice line items from billable work units.

    Each line item represents one (project, user) pair with:
      - aggregated billable hours
      - effective rate (contract rate preferred)
      - total amount
      - flags (e.g. rate_fallback, role_mismatch)

    Returns:
        {
            "invoice_lines":       list of line-item dicts,
            "project_subtotals":   {project: total_amount},
            "grand_total":         float,
            "billable_hours_total": float,
            "line_item_count":     int,
            "warnings":            list of warning strings,
        }
    """
    projects_model = contract_model.get("projects", {})
    billable_units = reconciled.get("billable_units", [])
    warnings: list[str] = []

    # Group hours and collect rate/role info per (project, user)
    group_hours:  dict = defaultdict(float)
    group_rate:   dict = {}
    group_role:   dict = {}
    group_flags:  dict = defaultdict(list)

    for wu in billable_units:
        proj = wu.get("project", "")
        user = wu.get("user", "")
        key  = (proj, user)

        group_hours[key] += wu.get("hours_declared", 0.0)

        if key not in group_rate:
            contract_rate, role = _contract_rate_and_role(user, proj, projects_model)
            if contract_rate:
                group_rate[key] = contract_rate
                group_role[key] = role
            else:
                # Fallback: canonical rate → timesheet rate
                rate = wu.get("canonical_rate") or wu.get("hourly_rate", 0.0)
                group_rate[key] = rate
                group_role[key] = ""
                group_flags[key].append("rate_fallback")
                warnings.append(
                    f"{user} on '{proj}': no contract rate found — using timesheet rate ${rate}/hr"
                )

        if wu.get("role_mismatch") and "role_mismatch" not in group_flags[key]:
            group_flags[key].append("role_mismatch")
            warnings.append(
                f"{user} on '{proj}': user not listed in contract team — "
                "verify role before sending invoice"
            )

    # Build line items
    invoice_lines: list[dict] = []
    proj_subtotals: dict[str, float] = defaultdict(float)

    for (proj, user), hours in group_hours.items():
        rate   = group_rate.get((proj, user), 0.0)
        amount = round(hours * rate, 2)
        role   = group_role.get((proj, user), "")
        flags  = group_flags.get((proj, user), [])

        invoice_lines.append({
            "project": proj,
            "user":    user,
            "role":    role,
            "hours":   round(hours, 2),
            "rate":    rate,
            "amount":  amount,
            "billable": True,
            "flags":   flags,
        })
        proj_subtotals[proj] += amount

    # Sort lines: project ASC, amount DESC
    invoice_lines.sort(key=lambda l: (l["project"], -l["amount"]))

    grand_total = round(sum(proj_subtotals.values()), 2)

    return {
        "invoice_lines":        invoice_lines,
        "project_subtotals":    {p: round(v, 2) for p, v in proj_subtotals.items()},
        "grand_total":          grand_total,
        "billable_hours_total": round(sum(l["hours"] for l in invoice_lines), 2),
        "line_item_count":      len(invoice_lines),
        "warnings":             warnings,
    }
