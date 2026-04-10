"""
Revenue Intelligence Report — clean card-based layout.

Design principles:
  - No charts or bar graphs — findings speak for themselves.
  - Every finding includes a source evidence trail (filename, row, clause).
  - Grouped by business impact: Revenue Leakage → Compliance → Invoice → Data Quality.
  - Collapsible sections to reduce visual overwhelm.
  - Actionable hints on each card.
"""
import html
import os
from collections import defaultdict, Counter
from datetime import date as date_cls

OUT_DIR = os.environ.get("OUT_DIR", "output")

# ---------------------------------------------------------------------------
# Severity palette
# ---------------------------------------------------------------------------

SEV_BG    = {"CRITICAL": "#fef2f2", "WARNING": "#fffbeb", "INFO": "#eff6ff"}
SEV_BORDER = {"CRITICAL": "#fca5a5", "WARNING": "#fde68a", "INFO": "#bfdbfe"}
SEV_COLOR = {"CRITICAL": "#dc2626", "WARNING": "#d97706", "INFO": "#2563eb"}
SEV_BADGE = {
    "CRITICAL": "background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:700;letter-spacing:.03em",
    "WARNING":  "background:#d97706;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:700;letter-spacing:.03em",
    "INFO":     "background:#2563eb;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:700;letter-spacing:.03em",
}


def esc(s: object) -> str:
    return html.escape(str(s) if s is not None else "")


def badge(sev: str) -> str:
    return f'<span style="{SEV_BADGE.get(sev, SEV_BADGE["INFO"])}">{esc(sev)}</span>'


# ---------------------------------------------------------------------------
# Source evidence — maps check/finding type → source files
# ---------------------------------------------------------------------------

# What data files are implicated per legacy check
CHECK_SOURCES = {
    "CHECK-1":  ["kimai_timesheets.csv"],
    "CHECK-2":  ["kimai_timesheets.csv"],
    "CHECK-3":  ["kimai_timesheets.csv", "hr_leave.csv / calendar_leave.csv"],
    "CHECK-4":  ["kimai_timesheets.csv", "hr_assignments.csv"],
    "CHECK-5":  ["kimai_timesheets.csv", "pm_projects.csv"],
    "CHECK-6":  ["kimai_timesheets.csv", "hr_employees.csv"],
    "CHECK-7":  ["kimai_timesheets.csv"],
    "CHECK-8":  ["kimai_timesheets.csv"],
    "CHECK-9":  ["kimai_timesheets.csv"],
    "CHECK-10": ["kimai_timesheets.csv", "hr_employees.csv"],
    "CHECK-11": ["kimai_timesheets.csv"],
    "CHECK-12": ["slack_activity.csv / git commits", "kimai_timesheets.csv (missing)"],
    "CHECK-13": ["kimai_timesheets.csv"],
    "CHECK-14": ["kimai_timesheets.csv", "calendar_holidays.csv"],
    "CHECK-15": ["kimai_timesheets.csv", "pm_projects.csv"],
}

# What data files are implicated per leakage/compliance finding type
LEAKAGE_SOURCES = {
    "rate_mismatch":         ["kimai_timesheets.csv (hourly_rate)", "hr_employees.csv (canonical rate)"],
    "unlogged_work":         ["slack_activity.csv", "kimai_timesheets.csv (entry missing)"],
    "cap_overage":           ["kimai_timesheets.csv", "SOW documents (monthly_hours clause)"],
    "scope_creep_untagged":  ["slack_activity.csv"],
    "archived_project_hours":["kimai_timesheets.csv", "pm_projects.csv (status=archived)"],
}

COMPLIANCE_SOURCES = {
    "unauthorized_overtime":        ["kimai_timesheets.csv", "HR guidelines (overtime policy)"],
    "leave_day_billing":            ["kimai_timesheets.csv", "hr_leave.csv / calendar_leave.csv"],
    "public_holiday_billing":       ["kimai_timesheets.csv", "calendar_holidays.csv"],
    "deactivated_employee_billing": ["kimai_timesheets.csv", "hr_employees.csv (status=deactivated)"],
    "archived_project_billing":     ["kimai_timesheets.csv", "pm_projects.csv (status=archived)"],
    "unassigned_project_billing":   ["kimai_timesheets.csv", "hr_assignments.csv (assignment missing)"],
}

# Recommended action per legacy check
CHECK_ACTIONS = {
    "CHECK-1":  "Fix or remove the invalid timestamp in kimai_timesheets.csv.",
    "CHECK-2":  "Adjust the time range of one entry to eliminate the overlap.",
    "CHECK-3":  "Reverse the timesheet entry or revise the leave status in hr_leave.csv.",
    "CHECK-4":  "Add the project to hr_assignments.csv or remove the timesheet entry.",
    "CHECK-5":  "Re-tag hours to an active project or reactivate the project in pm_projects.csv.",
    "CHECK-6":  "Correct the hourly_rate in kimai_timesheets.csv to match hr_employees.csv.",
    "CHECK-7":  "Add a valid activity type to the timesheet entry.",
    "CHECK-8":  "Add a description to the timesheet entry.",
    "CHECK-9":  "Assign a project to the timesheet entry.",
    "CHECK-10": "Verify whether the employee was active — remove or approve entries accordingly.",
    "CHECK-11": "Confirm weekend work was legitimate; add client approval note if billable.",
    "CHECK-12": "Chase the missing timesheet or confirm the Slack/git activity was non-billable.",
    "CHECK-13": "Recalculate and correct the hours field to match begin–end timestamps.",
    "CHECK-14": "Confirm client pre-approved billing on this public holiday.",
    "CHECK-15": "Align with the client before including over-budget hours on the invoice.",
}

LEAKAGE_ACTIONS = {
    "rate_mismatch":         "Update the hourly_rate in kimai_timesheets.csv to match the canonical rate.",
    "unlogged_work":         "Chase a timesheet entry from this user for the date mentioned in Slack.",
    "cap_overage":           "Get written pre-approval from the client before billing the overage hours.",
    "scope_creep_untagged":  "Raise a formal change order before billing; document client approval.",
    "archived_project_hours":"Re-tag these hours to an active project code, or seek client approval.",
}

COMPLIANCE_ACTIONS = {
    "unauthorized_overtime":        "Obtain and attach written approval from client/manager before billing.",
    "leave_day_billing":            "Reverse the timesheet entry or revise the leave record.",
    "public_holiday_billing":       "Confirm written client approval; attach to invoice as a note.",
    "deactivated_employee_billing": "Remove entries or reinstate the employee if work was legitimate.",
    "archived_project_billing":     "Re-tag to an active project or reactivate the project code.",
    "unassigned_project_billing":   "Add assignment in hr_assignments.csv or remove the billing entry.",
}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _model_short(model: str) -> str:
    if "opus" in model:
        return "opus"
    if "sonnet" in model:
        return "sonnet"
    if "haiku" in model:
        return "haiku"
    return model.split("-")[-1]


def _source_chips(sources: list) -> str:
    """Render a row of small source-file chips."""
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;background:#f3f4f6;'
        f'border:1px solid #e5e7eb;border-radius:4px;padding:2px 8px;font-size:0.7rem;'
        f'color:#374151;margin:2px 4px 2px 0;white-space:nowrap">'
        f'<span style="color:#6b7280">&#128196;</span>{esc(s)}</span>'
        for s in sources
    )
    return f'<div style="margin-top:8px;display:flex;flex-wrap:wrap">{chips}</div>'


def _action_hint(text: str) -> str:
    return (
        f'<div style="margin-top:8px;padding:6px 10px;background:#f0fdf4;border-left:3px solid #16a34a;'
        f'border-radius:0 4px 4px 0;font-size:0.78rem;color:#166534">'
        f'<strong>Action:</strong> {esc(text)}</div>'
    )


def _section(title: str, count: int, sev_color: str, body_html: str, section_id: str) -> str:
    """Collapsible section wrapper."""
    count_badge = (
        f'<span style="background:{sev_color};color:#fff;border-radius:12px;'
        f'padding:1px 10px;font-size:0.75rem;font-weight:700;margin-left:8px">{count}</span>'
        if count else ""
    )
    return f"""
<div class="card" style="margin-bottom:16px">
  <details open>
    <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;
                    justify-content:space-between;padding:0;user-select:none">
      <span style="font-size:1rem;font-weight:700;color:#111827">
        {esc(title)}{count_badge}
      </span>
      <span style="font-size:0.75rem;color:#9ca3af">▲ collapse</span>
    </summary>
    <div style="margin-top:16px">{body_html}</div>
  </details>
</div>"""


# ---------------------------------------------------------------------------
# Table + accordion helpers
# ---------------------------------------------------------------------------

def _table_wrap(headers: list, rows_html: str) -> str:
    """Scrollable table with standard column headers."""
    th_style = (
        "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;"
        "white-space:nowrap;text-align:left;background:#f9fafb"
    )
    th_cells = "".join(f'<th style="{th_style}">{esc(h)}</th>' for h in headers)
    return (
        f'<div style="overflow:auto;max-height:320px;margin-top:10px;'
        f'border:1px solid #e5e7eb;border-radius:6px">'
        f'<table style="width:100%;border-collapse:collapse;font-size:0.82rem">'
        f'<thead style="position:sticky;top:0;z-index:1"><tr>{th_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
    )


def _accordion(title: str, count: int, sev: str, body_html: str, open_: bool = False) -> str:
    """Inner accordion item — a collapsible finding group within a section."""
    color  = SEV_COLOR.get(sev, "#374151")
    bg     = SEV_BG.get(sev, "#f9fafb")
    border = SEV_BORDER.get(sev, "#e5e7eb")
    count_pill = (
        f'<span style="background:{color};color:#fff;border-radius:10px;'
        f'padding:1px 8px;font-size:0.72rem;font-weight:700;margin-left:6px">{count}</span>'
    )
    open_attr = " open" if open_ else ""
    return (
        f'<details{open_attr} style="border:1px solid {border};border-radius:6px;'
        f'margin-bottom:8px;background:{bg}">'
        f'<summary style="cursor:pointer;list-style:none;padding:10px 14px;'
        f'display:flex;align-items:center;gap:8px;user-select:none">'
        f'{badge(sev)}'
        f'<span style="font-weight:600;font-size:0.87rem;color:#111827">{esc(title)}</span>'
        f'{count_pill}'
        f'</summary>'
        f'<div style="padding:0 14px 14px">{body_html}</div>'
        f'</details>'
    )


# ---------------------------------------------------------------------------
# Per-section renderers
# ---------------------------------------------------------------------------

def _render_legacy_issues(issues: list, hours_issues: list) -> str:
    """Render legacy check findings grouped by check type as accordion + table."""
    from audit.checks import LABELS

    by_check = defaultdict(list)
    for issue in issues:
        if issue["check"] == "CHECK-13":
            continue
        by_check[issue["check"]].append(issue)

    if not by_check:
        return '<p style="color:#6b7280;font-style:italic">No issues found.</p>'

    SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    check_sev = {}
    for c, items in by_check.items():
        sevs = Counter(i["severity"] for i in items)
        check_sev[c] = "CRITICAL" if sevs["CRITICAL"] else ("WARNING" if sevs["WARNING"] else "INFO")

    check_order = sorted(by_check.keys(), key=lambda c: (SEV_ORDER[check_sev[c]], -len(by_check[c])))

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    parts = []
    for i, check in enumerate(check_order):
        items   = by_check[check]
        label   = LABELS.get(check, check)
        sev     = check_sev[check]
        sources = CHECK_SOURCES.get(check, ["kimai_timesheets.csv"])
        action  = CHECK_ACTIONS.get(check, "")

        rows_html = ""
        for issue in items[:50]:
            detail = issue.get("detail", "")
            clean  = detail
            if clean.startswith("Row ") and ": " in clean:
                clean = clean.split(": ", 1)[1]
            elif clean.startswith("Rows ") and ": " in clean:
                clean = clean.split(": ", 1)[1]
            sev_i = issue.get("severity", sev)
            rows_html += (
                f'<tr>'
                f'<td style="{td}">{badge(sev_i)}</td>'
                f'<td style="{td}">{esc(issue.get("user",""))}</td>'
                f'<td style="{td}">{esc(issue.get("date",""))}</td>'
                f'<td style="{td}">{esc(issue.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(clean or issue.get("brief",""))}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += (
                f'<tr><td colspan="5" style="{td};color:#9ca3af;font-style:italic">'
                f'… and {len(items)-50} more findings.</td></tr>'
            )

        table = _table_wrap(["Sev", "User", "Date", "Project", "Detail"], rows_html)
        body  = (_action_hint(action) if action else "") + _source_chips(sources) + table
        parts.append(_accordion(f"{check} — {label}", len(items), sev, body, open_=(i == 0)))

    # CHECK-13 (Hours accuracy)
    c13 = [i for i in issues if i["check"] == "CHECK-13"]
    if c13:
        rows_html = ""
        for issue in c13[:50]:
            detail = issue.get("detail", "")
            clean  = detail.split(": ", 1)[1] if ": " in detail else detail
            rows_html += (
                f'<tr>'
                f'<td style="{td}">{esc(issue.get("user",""))}</td>'
                f'<td style="{td}">{esc(issue.get("date",""))}</td>'
                f'<td style="{td};color:#374151">{esc(clean or issue.get("brief",""))}</td>'
                f'</tr>'
            )
        if len(c13) > 50:
            rows_html += (
                f'<tr><td colspan="3" style="{td};color:#9ca3af;font-style:italic">'
                f'… and {len(c13)-50} more findings.</td></tr>'
            )
        table = _table_wrap(["User", "Date", "Detail"], rows_html)
        body  = _action_hint(CHECK_ACTIONS["CHECK-13"]) + _source_chips(CHECK_SOURCES["CHECK-13"]) + table
        parts.append(_accordion("CHECK-13 — Hours Field Accuracy", len(c13), "INFO", body))

    return "".join(parts)


def _render_leakage(leakage: dict) -> str:
    findings = leakage.get("findings", [])
    if not findings:
        return '<p style="color:#6b7280;font-style:italic">No leakage signals detected.</p>'

    by_type = defaultdict(list)
    for f in findings:
        by_type[f["type"]].append(f)

    SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    type_order = sorted(
        by_type.keys(),
        key=lambda t: (
            SEV_ORDER.get(by_type[t][0].get("severity", "INFO"), 2),
            -sum(f.get("estimated_impact") or 0 for f in by_type[t]),
        ),
    )

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    parts = []
    for i, ftype in enumerate(type_order):
        items        = by_type[ftype]
        label        = ftype.replace("_", " ").title()
        sev          = items[0].get("severity", "INFO")
        total_impact = sum(f.get("estimated_impact") or 0 for f in items)
        sources      = LEAKAGE_SOURCES.get(ftype, ["kimai_timesheets.csv"])
        action       = LEAKAGE_ACTIONS.get(ftype, "Review and resolve before invoicing.")

        rows_html = ""
        for f in items[:50]:
            impact     = f.get("estimated_impact")
            impact_str = f"${impact:,.2f}" if impact else "—"
            rows_html += (
                f'<tr>'
                f'<td style="{td};font-weight:600">{esc(f.get("user",""))}</td>'
                f'<td style="{td}">{esc(f.get("date","") or "")}</td>'
                f'<td style="{td}">{esc(f.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(f.get("description",""))}</td>'
                f'<td style="{td};text-align:right;font-weight:600;color:#dc2626">{impact_str}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += (
                f'<tr><td colspan="5" style="{td};color:#9ca3af;font-style:italic">'
                f'… and {len(items)-50} more findings.</td></tr>'
            )

        title_str = f"{label}"
        if total_impact:
            title_str += f" — ${total_impact:,.0f} at risk"

        table = _table_wrap(["User", "Date", "Project", "Description", "Impact (USD)"], rows_html)
        body  = _action_hint(action) + _source_chips(sources) + table
        parts.append(_accordion(title_str, len(items), sev, body, open_=(i == 0)))

    return "".join(parts)


def _render_compliance(compliance: dict) -> str:
    findings = compliance.get("findings", [])
    if not findings:
        return '<p style="color:#6b7280;font-style:italic">No compliance issues found.</p>'

    SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    by_type = defaultdict(list)
    for f in findings:
        by_type[f["type"]].append(f)

    type_order = sorted(
        by_type.keys(),
        key=lambda t: (SEV_ORDER.get(by_type[t][0].get("severity", "INFO"), 2), -len(by_type[t])),
    )

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    parts = []
    for i, ftype in enumerate(type_order):
        items   = by_type[ftype]
        sev     = items[0].get("severity", "CRITICAL")
        label   = ftype.replace("_", " ").title()
        sources = COMPLIANCE_SOURCES.get(ftype, ["kimai_timesheets.csv"])
        action  = COMPLIANCE_ACTIONS.get(ftype, "Resolve before sending invoice.")
        clause  = items[0].get("contract_clause")
        if clause:
            sources = sources + [f"Policy: {clause}"]

        rows_html = ""
        for f in items[:50]:
            rows_html += (
                f'<tr>'
                f'<td style="{td};font-weight:600">{esc(f.get("user",""))}</td>'
                f'<td style="{td}">{esc(f.get("date","") or "")}</td>'
                f'<td style="{td}">{esc(f.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(f.get("description",""))}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += (
                f'<tr><td colspan="4" style="{td};color:#9ca3af;font-style:italic">'
                f'… and {len(items)-50} more findings.</td></tr>'
            )

        table = _table_wrap(["User", "Date", "Project", "Description"], rows_html)
        body  = _action_hint(action) + _source_chips(sources) + table
        parts.append(_accordion(label, len(items), sev, body, open_=(i == 0)))

    return "".join(parts)


def _render_slack_unlogged(slack: dict) -> str:
    unlogged = slack.get("work_without_timesheet", [])
    if not unlogged:
        return '<p style="color:#6b7280;font-style:italic">No unlogged Slack work signals found.</p>'

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    rows_html = ""
    for s in unlogged[:60]:
        channel     = s.get("channel", "")
        channel_str = f"#{channel}" if channel else "—"
        rows_html += (
            f'<tr>'
            f'<td style="{td};font-weight:600">{esc(s["user"])}</td>'
            f'<td style="{td}">{esc(s["date"])}</td>'
            f'<td style="{td};color:#6b7280">{esc(channel_str)}</td>'
            f'<td style="{td};color:#374151;font-style:italic">{esc(s["text"][:200])}</td>'
            f'</tr>'
        )
    if len(unlogged) > 60:
        rows_html += (
            f'<tr><td colspan="4" style="{td};color:#9ca3af;font-style:italic">'
            f'… and {len(unlogged)-60} more signals.</td></tr>'
        )

    table = _table_wrap(["User", "Date", "Channel", "Slack Message"], rows_html)
    body  = (
        _action_hint("Chase a timesheet entry from each user for the listed date.")
        + _source_chips(["slack_activity.csv", "kimai_timesheets.csv (entry missing)"])
        + table
    )
    return _accordion(f"Unlogged Work Signals", len(unlogged), "WARNING", body, open_=True)


def _render_invoice(invoice: dict) -> str:
    lines    = invoice.get("invoice_lines", [])
    subtotals = invoice.get("project_subtotals", {})
    warnings  = invoice.get("warnings", [])
    grand     = invoice.get("grand_total", 0)
    total_h   = invoice.get("billable_hours_total", 0)

    if not lines:
        return '<p style="color:#6b7280;font-style:italic">No billable work units found.</p>'

    warning_html = ""
    for w in warnings:
        warning_html += (
            f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:4px;'
            f'padding:6px 12px;margin-bottom:6px;font-size:0.8rem;color:#78350f">'
            f'&#9888; {esc(w)}</div>'
        )

    # Group lines by project
    by_proj = defaultdict(list)
    for l in lines:
        by_proj[l["project"]].append(l)

    parts = [warning_html]
    th = ("padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;"
          "color:#6b7280;border-bottom:2px solid #e5e7eb;white-space:nowrap")

    for proj in sorted(by_proj.keys()):
        proj_lines  = by_proj[proj]
        proj_total  = subtotals.get(proj, 0)
        parts.append(
            f'<div style="font-size:0.82rem;font-weight:700;color:#374151;'
            f'margin:16px 0 6px;display:flex;justify-content:space-between">'
            f'<span>{esc(proj)}</span>'
            f'<span style="color:#16a34a">${proj_total:,.2f}</span>'
            f'</div>'
        )
        parts.append(
            f'<div style="overflow-x:auto;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:12px">'
            f'<table style="width:100%;border-collapse:collapse;font-size:0.82rem">'
            f'<thead><tr>'
            f'<th style="{th};text-align:left">User</th>'
            f'<th style="{th};text-align:left">Role</th>'
            f'<th style="{th};text-align:right">Hours</th>'
            f'<th style="{th};text-align:right">Rate ($/hr)</th>'
            f'<th style="{th};text-align:right">Amount</th>'
            f'<th style="{th}">Flags</th>'
            f'</tr></thead><tbody>'
        )
        for line in proj_lines:
            flag_html = " ".join(
                f'<span style="background:#fee2e2;color:#dc2626;padding:1px 6px;'
                f'border-radius:3px;font-size:0.68rem;font-weight:600">{esc(fl)}</span>'
                for fl in line.get("flags", [])
            )
            parts.append(
                f'<tr style="border-bottom:1px solid #f3f4f6">'
                f'<td style="padding:7px 12px;font-weight:600">{esc(line["user"])}</td>'
                f'<td style="padding:7px 12px;color:#6b7280">{esc(line.get("role",""))}</td>'
                f'<td style="padding:7px 12px;text-align:right">{line["hours"]:.2f}</td>'
                f'<td style="padding:7px 12px;text-align:right">{line["rate"]:.2f}</td>'
                f'<td style="padding:7px 12px;text-align:right;font-weight:700;color:#16a34a">'
                f'${line["amount"]:,.2f}</td>'
                f'<td style="padding:7px 12px">{flag_html}</td>'
                f'</tr>'
            )
        parts.append('</tbody></table></div>')

    parts.append(
        f'<div style="text-align:right;font-size:1rem;font-weight:700;color:#111827;'
        f'padding:10px 0;border-top:2px solid #e5e7eb;margin-top:8px">'
        f'Grand Total: <span style="color:#16a34a;font-size:1.2rem">${grand:,.2f}</span> '
        f'<span style="color:#9ca3af;font-size:0.78rem;font-weight:400">'
        f'({total_h:.1f} billable hours)</span></div>'
    )
    parts.append(_source_chips(["kimai_timesheets.csv (billable entries)", "SOW documents (contract rates)"]))

    return "".join(parts)


def _render_budget(
    proj_budget_hours: dict,
    proj_budget_cost:  dict,
    proj_actual_hours: dict,
    proj_actual_cost:  dict,
) -> str:
    if not proj_budget_hours:
        return '<p style="color:#6b7280;font-style:italic">No project budget data found (pm_projects.csv).</p>'

    all_projs = sorted(set(proj_budget_hours) | set(proj_actual_hours))
    td = "padding:8px 12px;border-bottom:1px solid #f3f4f6;vertical-align:middle"

    rows_html = ""
    for proj in all_projs:
        bh  = proj_budget_hours.get(proj, 0)
        ah  = proj_actual_hours.get(proj, 0)
        bc  = proj_budget_cost.get(proj, 0)
        ac  = proj_actual_cost.get(proj, 0)
        pct = (ah / bh * 100) if bh > 0 else None

        if pct is None:
            status_html = '<span style="color:#9ca3af;font-size:0.75rem">no budget</span>'
            row_bg = ""
        elif pct > 100:
            status_html = (
                f'<span style="background:#dc2626;color:#fff;border-radius:4px;'
                f'padding:1px 8px;font-size:0.72rem;font-weight:700">OVER {pct:.0f}%</span>'
            )
            row_bg = "background:#fef2f2;"
        elif pct > 90:
            status_html = (
                f'<span style="background:#d97706;color:#fff;border-radius:4px;'
                f'padding:1px 8px;font-size:0.72rem;font-weight:700">NEAR {pct:.0f}%</span>'
            )
            row_bg = "background:#fffbeb;"
        else:
            status_html = f'<span style="color:#16a34a;font-size:0.78rem;font-weight:600">{pct:.0f}% used</span>'
            row_bg = ""

        h_delta = ah - bh
        c_delta = ac - bc
        h_color = "#dc2626" if h_delta > 0 else "#16a34a"
        c_color = "#dc2626" if c_delta > 0 else "#16a34a"
        h_delta_str = (
            f'<span style="color:{h_color}">{"+" if h_delta > 0 else ""}{h_delta:,.1f}h</span>'
        ) if bh else "—"
        c_delta_str = (
            f'<span style="color:{c_color}">{"+" if c_delta > 0 else ""}${c_delta:,.0f}</span>'
        ) if bc else "—"

        rows_html += (
            f'<tr style="{row_bg}">'
            f'<td style="{td};font-weight:600">{esc(proj)}</td>'
            f'<td style="{td};text-align:center">{status_html}</td>'
            f'<td style="{td};text-align:right">{ah:,.1f}h</td>'
            f'<td style="{td};text-align:right">{bh:,.0f}h</td>'
            f'<td style="{td};text-align:right">{h_delta_str}</td>'
            f'<td style="{td};text-align:right">${ac:,.0f}</td>'
            f'<td style="{td};text-align:right">${bc:,.0f}</td>'
            f'<td style="{td};text-align:right">{c_delta_str}</td>'
            f'</tr>'
        )

    table  = _table_wrap(
        ["Project", "Status", "Actual Hrs", "Budget Hrs", "Δ Hours",
         "Actual Cost", "Budget Cost", "Δ Cost"],
        rows_html,
    )
    source = _source_chips(["pm_projects.csv (budget_hours, budget_cost)", "kimai_timesheets.csv (actuals)"])
    return table + source


def _render_data_quality(work_units_data) -> str:
    """Render data quality issues from normalisation agent output."""
    if not work_units_data:
        return ""
    qi = work_units_data.get("data_quality_issues", [])
    if not qi:
        return '<p style="color:#6b7280;font-style:italic">No data quality issues found.</p>'

    by_flag = defaultdict(list)
    for issue in qi:
        by_flag[issue["flag"]].append(issue)

    FLAG_PRIORITY = [
        "invalid_timestamp", "hours_mismatch", "missing_project",
        "missing_activity", "missing_description", "weekend_entry", "public_holiday_entry",
    ]
    ordered = [f for f in FLAG_PRIORITY if f in by_flag] + [f for f in by_flag if f not in FLAG_PRIORITY]

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    parts = []
    for i, flag in enumerate(ordered):
        items = by_flag[flag]
        label = flag.replace("_", " ").title()

        rows_html = ""
        for issue in items[:50]:
            rows_html += (
                f'<tr>'
                f'<td style="{td};font-weight:600">{esc(issue.get("user",""))}</td>'
                f'<td style="{td}">{esc(issue.get("date",""))}</td>'
                f'<td style="{td}">{esc(issue.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(issue.get("description",""))}</td>'
                f'<td style="{td};color:#9ca3af;font-size:0.72rem">WU-{esc(str(issue.get("work_unit_id","")))}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += (
                f'<tr><td colspan="5" style="{td};color:#9ca3af;font-style:italic">'
                f'… and {len(items)-50} more {label} issues.</td></tr>'
            )

        table = _table_wrap(["User", "Date", "Project", "Description", "WU ID"], rows_html)
        body  = _source_chips(["kimai_timesheets.csv"]) + table
        parts.append(_accordion(label, len(items), "INFO", body, open_=(i == 0)))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Key takeaways + invoice readiness
# ---------------------------------------------------------------------------

def _key_takeaways_panel(
    takeaways,
    leakage_findings,
    compliance_findings,
    invoice_draft,
) -> str:
    # Determine invoice readiness
    n_crit_compliance = compliance_findings.get("critical_count", 0) if compliance_findings else 0
    n_crit_leakage    = leakage_findings.get("critical_count", 0)    if leakage_findings    else 0
    has_invoice       = bool(invoice_draft and invoice_draft.get("grand_total", 0) > 0)
    flagged_lines     = sum(
        1 for l in (invoice_draft or {}).get("invoice_lines", []) if l.get("flags")
    ) if invoice_draft else 0

    if n_crit_compliance > 0:
        status       = "ACTION REQUIRED"
        status_color = "#dc2626"
        status_bg    = "#fef2f2"
        status_reason = f"{n_crit_compliance} critical compliance issue(s) must be resolved before sending."
    elif n_crit_leakage > 0:
        status       = "NEEDS REVIEW"
        status_color = "#d97706"
        status_bg    = "#fffbeb"
        status_reason = f"{n_crit_leakage} revenue leakage issue(s) require attention."
    elif flagged_lines > 0:
        status       = "NEEDS REVIEW"
        status_color = "#d97706"
        status_bg    = "#fffbeb"
        status_reason = f"{flagged_lines} invoice line(s) have rate/role flags to confirm."
    elif has_invoice:
        status       = "READY"
        status_color = "#16a34a"
        status_bg    = "#f0fdf4"
        status_reason = "No critical blockers found. Review warnings before sending."
    else:
        status       = "INCOMPLETE"
        status_color = "#6b7280"
        status_bg    = "#f9fafb"
        status_reason = "Intelligence pipeline has not completed — run all agents first."

    readiness_html = (
        f'<div style="display:flex;align-items:center;gap:14px;padding:14px 18px;'
        f'background:{status_bg};border:1px solid {status_color}40;border-radius:8px;margin-bottom:16px">'
        f'<span style="background:{status_color};color:#fff;padding:4px 14px;border-radius:6px;'
        f'font-size:0.82rem;font-weight:700;letter-spacing:.04em;white-space:nowrap">{status}</span>'
        f'<span style="font-size:0.85rem;color:#374151">{esc(status_reason)}</span>'
        f'</div>'
    )

    if not takeaways:
        return readiness_html

    items_html = "".join(
        f'<li style="margin-bottom:8px;font-size:0.87rem;color:#374151">{esc(t)}</li>'
        for t in takeaways
    )
    return (
        f'{readiness_html}'
        f'<ol style="margin:0;padding-left:20px">{items_html}</ol>'
    )


# ---------------------------------------------------------------------------
# Stat tiles row
# ---------------------------------------------------------------------------

def _stat_tiles(
    total_entries:       int,
    n_crit:              int,
    n_warn:              int,
    n_info:              int,
    leakage_findings,
    compliance_findings,
    invoice_draft,
    slack_signals,
) -> str:
    tiles = [
        ("#f0fdf4", "#16a34a", f"{total_entries:,}", "Entries Audited"),
        ("#fef2f2", "#dc2626", f"{n_crit:,}", "Critical Issues"),
        ("#fffbeb", "#d97706", f"{n_warn:,}", "Warnings"),
    ]
    if leakage_findings:
        impact = leakage_findings.get("total_estimated_impact", 0)
        tiles.append(("#fef2f2", "#dc2626", f"${impact:,.0f}", "Revenue at Risk"))
    if invoice_draft:
        grand = invoice_draft.get("grand_total", 0)
        tiles.append(("#f0fdf4", "#16a34a", f"${grand:,.0f}", "Invoice Draft Total"))
    if slack_signals:
        unlogged = slack_signals.get("unlogged_work_count", 0)
        tiles.append(("#eff6ff", "#2563eb", f"{unlogged}", "Unlogged Slack Signals"))
    if compliance_findings:
        cc = compliance_findings.get("critical_count", 0)
        tiles.append(("#fef2f2", "#dc2626", f"{cc}", "Compliance Blockers"))

    tile_html = "".join(
        f'<div style="flex:1;min-width:120px;background:{bg};border-radius:8px;padding:14px 16px">'
        f'<div style="font-size:1.6rem;font-weight:800;color:{color}">{val}</div>'
        f'<div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:.05em;'
        f'color:{color};opacity:.8;margin-top:2px">{lbl}</div>'
        f'</div>'
        for bg, color, val, lbl in tiles
    )
    return f'<div style="display:flex;gap:12px;flex-wrap:wrap">{tile_html}</div>'


# ---------------------------------------------------------------------------
# CSS + JS
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0; padding: 24px;
  background: #f3f4f6; color: #111827;
  line-height: 1.5;
}
.card {
  background: #fff; border-radius: 10px;
  box-shadow: 0 1px 4px rgba(0,0,0,.07);
  padding: 20px 24px; margin-bottom: 16px;
}
details summary::-webkit-details-marker { display: none; }
a { color: #2563eb; }
"""

_SEARCH_JS = """
<script>
(function() {
  var inp = document.getElementById('issue-search');
  if (!inp) return;
  inp.addEventListener('input', function() {
    var q = inp.value.toLowerCase();
    document.querySelectorAll('.finding-card').forEach(function(el) {
      el.style.display = (el.textContent.toLowerCase().includes(q)) ? '' : 'none';
    });
  });
})();
</script>
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate(
    issues: list,
    hours_issues: list,
    total_entries: int,
    key_takeaways: list = None,
    data_version: str = "v3",
    model: str = "claude-haiku-4-5-20251001",
    proj_budget_hours: dict = None,
    proj_budget_cost:  dict = None,
    proj_actual_hours: dict = None,
    proj_actual_cost:  dict = None,
    leakage_findings:    dict = None,
    compliance_findings: dict = None,
    invoice_draft:       dict = None,
    slack_signals:       dict = None,
    work_units_data:     dict = None,
) -> str:
    """
    Write output/audit_{version}_{model_short}_YYYY-MM-DD.html and return the file path.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    today       = date_cls.today().isoformat()
    model_short = _model_short(model)

    n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
    n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
    n_info = sum(1 for i in issues if i["severity"] == "INFO")

    # Include counts from agent pipeline findings
    if compliance_findings:
        n_crit += compliance_findings.get("critical_count", 0)
        n_warn += compliance_findings.get("warning_count", 0)
    if leakage_findings:
        n_crit += leakage_findings.get("critical_count", 0)
        n_warn += leakage_findings.get("warning_count", 0)

    # ---- Sections ----
    stat_tiles_html = _stat_tiles(
        total_entries, n_crit, n_warn, n_info,
        leakage_findings, compliance_findings, invoice_draft, slack_signals,
    )

    takeaways_html = _key_takeaways_panel(
        key_takeaways or [], leakage_findings, compliance_findings, invoice_draft
    )

    leakage_html    = _render_leakage(leakage_findings)    if leakage_findings    else ""
    compliance_html = _render_compliance(compliance_findings) if compliance_findings else ""
    slack_html      = _render_slack_unlogged(slack_signals) if slack_signals       else ""
    invoice_html    = _render_invoice(invoice_draft)        if invoice_draft        else ""
    budget_html     = _render_budget(
        proj_budget_hours or {}, proj_budget_cost or {},
        proj_actual_hours or {}, proj_actual_cost or {},
    )
    legacy_html     = _render_legacy_issues(issues, hours_issues)
    quality_html    = _render_data_quality(work_units_data)

    # ---- Wrap sections ----
    leakage_section = _section(
        "Revenue Leakage",
        leakage_findings.get("total_findings", 0) if leakage_findings else 0,
        "#dc2626", leakage_html, "leakage",
    ) if leakage_findings else ""

    compliance_section = _section(
        "Compliance Blockers",
        compliance_findings.get("total_findings", 0) if compliance_findings else 0,
        "#dc2626", compliance_html, "compliance",
    ) if compliance_findings else ""

    slack_section = _section(
        "Unlogged Work — Slack Signals",
        slack_signals.get("unlogged_work_count", 0) if slack_signals else 0,
        "#d97706", slack_html, "slack",
    ) if slack_signals else ""

    invoice_section = _section(
        "Invoice Draft",
        invoice_draft.get("line_item_count", 0) if invoice_draft else 0,
        "#16a34a", invoice_html, "invoice",
    ) if invoice_draft else ""

    budget_section = _section(
        "Project Budget vs Actuals",
        len(proj_budget_hours) if proj_budget_hours else 0,
        "#7c3aed", budget_html, "budget",
    ) if proj_budget_hours else ""

    legacy_section = _section(
        "Audit Check Findings",
        len([i for i in issues if i["check"] != "CHECK-13"]),
        "#374151", legacy_html, "legacy",
    )

    quality_section = _section(
        "Data Quality Issues",
        len(work_units_data.get("data_quality_issues", [])) if work_units_data else 0,
        "#6b7280", quality_html, "quality",
    ) if work_units_data else ""

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revenue Intelligence Report — {data_version} {today}</title>
<style>{_CSS}</style>
</head>
<body>

<!-- HEADER -->
<div class="card" style="margin-bottom:16px">
  <div style="display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:6px">
    <h1 style="margin:0;font-size:1.25rem;font-weight:800">Revenue Intelligence Report</h1>
    <span style="font-size:0.85rem;font-weight:700;color:#7c3aed">{esc(data_version)}</span>
    <span style="font-size:0.78rem;color:#9ca3af">model: {esc(model_short)}</span>
    <span style="font-size:0.78rem;color:#9ca3af">generated {today}</span>
  </div>
  {stat_tiles_html}
</div>

<!-- INVOICE STATUS + KEY TAKEAWAYS -->
<div class="card">
  <h2 style="margin:0 0 14px;font-size:1rem;font-weight:700">Invoice Status &amp; Key Insights</h2>
  {takeaways_html}
</div>

{leakage_section}
{compliance_section}
{slack_section}
{invoice_section}
{budget_section}
{legacy_section}
{quality_section}

{_SEARCH_JS}
</body>
</html>"""

    out_path = os.path.join(OUT_DIR, f"audit_{data_version}_{model_short}_{today}.html")
    with open(out_path, "w") as f:
        f.write(html_out)
    return out_path
