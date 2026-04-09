"""
Work Reconciliation Agent logic.

Aligns Work Units with project assignments and the ContractModel:
  - Marks each unit billable / non-billable with reasons
  - Detects duplicate timesheet entries
  - Flags role mismatches against the contract team roster
  - Computes per-project billable/non-billable hour totals
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional, Tuple


def _match_project(project: str, projects_model: dict) -> Tuple[Optional[str], Optional[dict]]:
    """Case-insensitive fuzzy match of a timesheet project name to a contract project."""
    p_lc = project.lower()
    for pname, pdata in projects_model.items():
        if pname.lower() in p_lc or p_lc in pname.lower():
            return pname, pdata
    return None, None


def _match_user_in_team(user: str, team_map: dict) -> Optional[dict]:
    """Return the contract team member dict for a user, or None."""
    u_lc = user.lower()
    for k, member in team_map.items():
        if k in u_lc or u_lc in k:
            return member
    return None


def reconcile_work(work_units: list[dict], contract_model: dict) -> dict:
    """
    Reconcile work units against assignments and the contract model.

    Returns:
        {
            "work_units":              all units, each enriched with billability fields,
            "billable_units":          subset that is billable,
            "non_billable_units":      subset that is non-billable,
            "billable_count":          int,
            "non_billable_count":      int,
            "total_billable_hours":    float,
            "total_non_billable_hours": float,
            "duplicates":              list of duplicate-pair dicts,
            "role_mismatches":         list of mismatch dicts,
            "project_totals":          {project: {billable_hours, non_billable_hours, users}},
        }
    """
    projects_model = contract_model.get("projects", {})

    billable_units:     list[dict] = []
    non_billable_units: list[dict] = []
    role_mismatches:    list[dict] = []

    # ---- Duplicate detection ----
    seen_entries: dict = {}
    duplicates:   list[dict] = []

    for wu in work_units:
        dup_key = (wu["user"], wu["date"], wu["project"], wu["begin"], wu["end"])
        if dup_key in seen_entries:
            duplicates.append({
                "work_unit_id":  wu["id"],
                "duplicate_of":  seen_entries[dup_key],
                "user":          wu["user"],
                "date":          wu["date"],
                "project":       wu["project"],
            })
        else:
            seen_entries[dup_key] = wu["id"]

    # ---- Billability & role checks ----
    for wu in work_units:
        reasons: list[str] = []

        if not wu.get("is_assigned"):
            reasons.append("not_assigned_to_project")
        if wu.get("is_on_leave"):
            reasons.append("on_approved_leave")
        if wu.get("is_deactivated"):
            reasons.append("employee_deactivated")
        if wu.get("is_archived_project"):
            reasons.append("project_archived")

        # Role mismatch against contract team
        project = wu.get("project", "")
        matched_pname, proj_contract = _match_project(project, projects_model)
        role_mismatch = None  # Optional[dict]

        if proj_contract:
            team_map = proj_contract.get("team_map", {})
            if team_map:
                member = _match_user_in_team(wu["user"], team_map)
                if member is None:
                    role_mismatch = {
                        "work_unit_id":   wu["id"],
                        "user":           wu["user"],
                        "project":        project,
                        "contract_project": matched_pname,
                        "description":    (
                            f"'{wu['user']}' not listed in contract team for "
                            f"'{matched_pname}' — billing may be disputed"
                        ),
                    }
                    role_mismatches.append(role_mismatch)

        is_billable = len(reasons) == 0
        enriched = {
            **wu,
            "is_billable":          is_billable,
            "non_billable_reasons": reasons,
            "contract_project":     matched_pname,
            "has_contract":         proj_contract is not None,
            "role_mismatch":        role_mismatch is not None,
        }

        (billable_units if is_billable else non_billable_units).append(enriched)

    # ---- Per-project totals ----
    proj_totals: dict = defaultdict(lambda: {
        "billable_hours":     0.0,
        "non_billable_hours": 0.0,
        "users":              set(),
    })
    for wu in billable_units + non_billable_units:
        proj = wu.get("project", "")
        h    = wu.get("hours_declared", 0.0)
        if wu["is_billable"]:
            proj_totals[proj]["billable_hours"] += h
        else:
            proj_totals[proj]["non_billable_hours"] += h
        proj_totals[proj]["users"].add(wu["user"])

    proj_totals_json = {
        p: {
            "billable_hours":     round(v["billable_hours"], 2),
            "non_billable_hours": round(v["non_billable_hours"], 2),
            "users":              sorted(v["users"]),
        }
        for p, v in proj_totals.items()
    }

    all_units = billable_units + non_billable_units

    return {
        "work_units":               all_units,
        "billable_units":           billable_units,
        "non_billable_units":       non_billable_units,
        "billable_count":           len(billable_units),
        "non_billable_count":       len(non_billable_units),
        "total_billable_hours":     round(sum(wu["hours_declared"] for wu in billable_units), 2),
        "total_non_billable_hours": round(sum(wu["hours_declared"] for wu in non_billable_units), 2),
        "duplicates":               duplicates,
        "role_mismatches":          role_mismatches,
        "project_totals":           proj_totals_json,
    }
