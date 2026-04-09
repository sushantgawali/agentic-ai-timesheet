"""
Contract Interpreter Agent logic.

Builds a structured ContractModel from SOW documents and HR guideline documents.
The ContractModel drives all downstream billing, leakage, and compliance checks.
"""
import re
from audit.loader import load_all

# Regex patterns for common contract rules inside guideline text
_OVERTIME_PATS = [
    r"overtime\s+(?:work\s+)?(?:requires?|needs?|must\s+have|requires?\s+written)\s+approval",
    r"(?:written|prior)\s+approval\s+(?:is\s+)?required\s+(?:for\s+)?overtime",
    r"pre.?approval\s+(?:is\s+)?(?:required|needed)\s+(?:for\s+)?overtime",
]
_LEAVE_TYPE_PAT   = re.compile(
    r"(?:types?\s+of\s+leave|leave\s+types?|leave\s+categories?)[:\s]+([^\n.]{5,120})",
    re.IGNORECASE,
)
_BILLING_EXCL_PAT = re.compile(
    r"((?:not\s+billable|non.?billable|exclude\s+from\s+billing|cannot\s+be\s+billed)[^\n.]{0,150})",
    re.IGNORECASE,
)
_BILLING_CAP_PAT = re.compile(
    r"(?:billing\s+cap|cap\s+of|maximum\s+(?:billable\s+)?hours?)[:\s]+([^\n.]{5,80})",
    re.IGNORECASE,
)


def build_contract_model() -> dict:
    """
    Build a ContractModel from SOW documents and HR guidelines.

    Returns:
        {
            "projects": {
                "<project_name>": {
                    "sow_reference":            str | None,
                    "client":                   str | None,
                    "effective_date":           str | None,
                    "end_date":                 str | None,
                    "monthly_value":            str | None,
                    "monthly_cap_hours":        float | None,   # sum of team monthly_hours
                    "billing_type":             "T&M" | "fixed",
                    "team":                     list of team member dicts,
                    "team_map":                 {name_lower: member_dict},
                    "requires_overtime_approval": bool,
                }
            },
            "global_rules": {
                "overtime_requires_approval": bool,
                "leave_types":               list[str],
                "billing_exclusions":        list[str],
                "billing_caps":              list[str],
                "raw_policy_excerpts":       list[{source, rule, excerpt}],
            },
            "sow_count":       int,
            "guideline_count": int,
        }
    """
    ctx            = load_all()
    sow_data       = ctx.get("sow_data", [])
    guidelines     = ctx.get("guidelines_data", [])

    # ------------------------------------------------------------------ #
    # Build per-project models from SOW documents                         #
    # ------------------------------------------------------------------ #
    projects: dict = {}
    for sow in sow_data:
        pname = (sow.get("project_name") or sow.get("filename", "unknown")).strip()

        team_map: dict = {}
        for member in sow.get("team", []):
            name = member.get("name", "").strip()
            if name:
                team_map[name.lower()] = {
                    "name":          name,
                    "role":          member.get("role", ""),
                    "allocation":    member.get("allocation", ""),
                    "rate":          float(member.get("rate", 0) or 0),
                    "monthly_hours": int(member.get("monthly_hours", 0) or 0),
                }

        total_monthly_hours = sum(
            m.get("monthly_hours", 0) for m in sow.get("team", [])
        )

        projects[pname] = {
            "sow_reference":              sow.get("sow_reference"),
            "client":                     sow.get("client"),
            "effective_date":             sow.get("effective_date"),
            "end_date":                   sow.get("end_date"),
            "monthly_value":              sow.get("monthly_value"),
            "monthly_cap_hours":          total_monthly_hours if total_monthly_hours > 0 else None,
            "billing_type":               "T&M",   # default; refined below if parseable
            "team":                       sow.get("team", []),
            "team_map":                   team_map,
            "requires_overtime_approval": False,    # overridden by global_rules below
        }

    # ------------------------------------------------------------------ #
    # Extract global rules from guideline documents                       #
    # ------------------------------------------------------------------ #
    global_rules: dict = {
        "overtime_requires_approval": False,
        "leave_types":               [],
        "billing_exclusions":        [],
        "billing_caps":              [],
        "raw_policy_excerpts":       [],
    }

    for doc in guidelines:
        text  = doc.get("text", "")
        fname = doc.get("filename", "")

        # Overtime approval requirement
        if not global_rules["overtime_requires_approval"]:
            for pat_str in _OVERTIME_PATS:
                m = re.search(pat_str, text, re.IGNORECASE)
                if m:
                    global_rules["overtime_requires_approval"] = True
                    global_rules["raw_policy_excerpts"].append({
                        "source":  fname,
                        "rule":    "overtime_requires_approval",
                        "excerpt": m.group(0)[:200],
                    })
                    break

        # Leave types
        m = _LEAVE_TYPE_PAT.search(text)
        if m:
            types_found = [t.strip() for t in re.split(r"[,;]", m.group(1)) if t.strip()]
            global_rules["leave_types"].extend(types_found)

        # Billing exclusions
        for m in _BILLING_EXCL_PAT.finditer(text):
            excl = m.group(1).strip()
            if excl not in global_rules["billing_exclusions"]:
                global_rules["billing_exclusions"].append(excl)

        # Billing caps
        for m in _BILLING_CAP_PAT.finditer(text):
            cap_text = m.group(0).strip()
            if cap_text not in global_rules["billing_caps"]:
                global_rules["billing_caps"].append(cap_text)

    global_rules["leave_types"] = list(set(global_rules["leave_types"]))

    # Propagate global overtime rule into each project
    if global_rules["overtime_requires_approval"]:
        for pname in projects:
            projects[pname]["requires_overtime_approval"] = True

    return {
        "projects":        projects,
        "global_rules":    global_rules,
        "sow_count":       len(sow_data),
        "guideline_count": len(guidelines),
    }
