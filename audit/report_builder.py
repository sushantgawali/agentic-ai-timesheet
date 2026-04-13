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
from datetime import date as date_cls, datetime as datetime_cls

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
    "CHECK-19": ["kimai_timesheets.csv"],
    "CHECK-20": ["kimai_timesheets.csv"],
    "CHECK-21": ["kimai_timesheets.csv", "hr_leave.csv", "calendar_leave.csv"],
    "CHECK-22": ["kimai_timesheets.csv"],
    "CHECK-23": ["kimai_timesheets.csv (submitted_at)"],
    "CHECK-24": ["kimai_timesheets.csv", "hr_employees.csv (missing)"],
    "CHECK-25": ["calendar_leave.csv", "hr_leave.csv (missing)"],
    "CHECK-26": ["slack_activity.csv", "hr_leave.csv (missing)", "calendar_leave.csv (missing)"],
    "CHECK-27": ["kimai_timesheets.csv"],
}

# What data files are implicated per leakage/compliance finding type
LEAKAGE_SOURCES = {
    "rate_mismatch":                ["kimai_timesheets.csv (hourly_rate)", "SOW documents (contract rate)", "hr_employees.csv (canonical rate fallback)"],
    "unlogged_work":                ["slack_activity.csv", "kimai_timesheets.csv (entry missing)"],
    "cap_overage":                  ["kimai_timesheets.csv", "SOW documents (monthly_hours clause)"],
    "scope_creep_untagged":         ["slack_activity.csv"],
    "archived_project_hours":       ["kimai_timesheets.csv", "pm_projects.csv (status=archived)"],
    "contract_hours_underbilling":  ["kimai_timesheets.csv", "hr_employees.csv (contract_hrs)"],
}

COMPLIANCE_SOURCES = {
    "unauthorized_overtime":          ["kimai_timesheets.csv", "HR guidelines (overtime policy)"],
    "leave_day_billing":              ["kimai_timesheets.csv", "hr_leave.csv / calendar_leave.csv"],
    "public_holiday_billing":         ["kimai_timesheets.csv", "calendar_holidays.csv"],
    "deactivated_employee_billing":   ["kimai_timesheets.csv", "hr_employees.csv (status=deactivated)"],
    "archived_project_billing":       ["kimai_timesheets.csv", "pm_projects.csv (status=archived)"],
    "unassigned_project_billing":     ["kimai_timesheets.csv", "hr_assignments.csv (assignment missing)"],
    "project_billing_after_end_date": ["kimai_timesheets.csv", "pm_projects.csv (end_date)"],
    "partial_day_leave_billing":      ["kimai_timesheets.csv", "calendar_leave.csv (all_day=false)"],
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
    "CHECK-19": "Remove the zero-duration entry or correct the begin/end timestamps.",
    "CHECK-20": "Verify with the employee that all hours were genuinely worked; split into correct days if multi-day work was logged on one entry.",
    "CHECK-21": "Confirm with the employee why fewer than 5h were logged. If half-day leave, add a record in hr_leave.csv or calendar_leave.csv.",
    "CHECK-22": "Ask the employee to break down how 8h was spent — exact round hours suggest manual entry rather than timer-based tracking.",
    "CHECK-23": "Discuss late filing with the employee. If the work was genuine, note in the invoice narrative. If not, remove the entries.",
    "CHECK-24": "Add the user to hr_employees.csv with a rate and status, or remove their timesheet entries if billing was unauthorised.",
    "CHECK-25": "Sync the calendar leave entry to hr_leave.csv so HR records are complete before payroll processing.",
    "CHECK-26": "Cross-check with the employee: if leave was taken, add an hr_leave entry. If the Slack message was misclassified, no action needed.",
    "CHECK-27": "Ask the employee to provide specific descriptions per day. Copy-pasted entries suggest bulk retroactive filing.",
}

LEAKAGE_ACTIONS = {
    "rate_mismatch":               "Update the hourly_rate in kimai_timesheets.csv to match the SOW-agreed rate (or HR canonical rate if no SOW rate exists).",
    "unlogged_work":               "Chase a timesheet entry from this user for the date mentioned in Slack.",
    "cap_overage":                 "Get written pre-approval from the client before billing the overage hours.",
    "scope_creep_untagged":        "Raise a formal change order before billing; document client approval.",
    "archived_project_hours":      "Re-tag these hours to an active project code, or seek client approval.",
    "contract_hours_underbilling": "Investigate the shortfall: confirm whether hours were logged to a different project, or chase missing timesheets from the employee.",
}

COMPLIANCE_ACTIONS = {
    "unauthorized_overtime":          "Obtain and attach written approval from client/manager before billing.",
    "leave_day_billing":              "Reverse the timesheet entry or revise the leave record.",
    "public_holiday_billing":         "Confirm written client approval; attach to invoice as a note.",
    "deactivated_employee_billing":   "Remove entries or reinstate the employee if work was legitimate.",
    "archived_project_billing":       "Re-tag to an active project or reactivate the project code.",
    "unassigned_project_billing":     "Add assignment in hr_assignments.csv or remove the billing entry.",
    "project_billing_after_end_date": "Confirm a contract extension was agreed with the client; update end_date in pm_projects.csv or remove the entry.",
    "partial_day_leave_billing":      "Adjust the timesheet to reflect only the worked portion of the day, or confirm client approved full-day billing.",
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


def _section(title: str, count: int, sev_color: str, body_html: str, section_id: str, open_: bool = True) -> str:
    """Collapsible section wrapper."""
    count_badge = (
        f'<span class="dyn-count" style="background:{sev_color};color:#fff;border-radius:12px;'
        f'padding:1px 10px;font-size:0.75rem;font-weight:700;margin-left:8px">{count}</span>'
        if count else ""
    )
    open_attr = " open" if open_ else ""
    return f"""
<div class="card" style="margin-bottom:16px">
  <details{open_attr}>
    <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;
                    justify-content:space-between;padding:0;user-select:none">
      <span style="font-size:1rem;font-weight:700;color:#111827">
        {esc(title)}{count_badge}
      </span>
      <span class="chevron" style="font-size:0.75rem;color:#9ca3af;display:inline-block">▶</span>
    </summary>
    <div style="margin-top:16px">{body_html}</div>
  </details>
</div>"""


def _tab_section(title: str, count: int, color: str, body_html: str, description: str = "") -> str:
    """Card wrapper for tab panel content — no outer collapsible."""
    count_badge = (
        f'<span style="background:{color};color:#fff;border-radius:12px;'
        f'padding:1px 10px;font-size:0.75rem;font-weight:700;margin-left:8px">{count}</span>'
    ) if count else ""
    desc_html = (
        f'<p style="margin:4px 0 16px;font-size:0.82rem;color:#6b7280">{esc(description)}</p>'
    ) if description else '<div style="margin-bottom:16px"></div>'
    return (
        f'<div class="card">'
        f'<h2 style="margin:0;font-size:1rem;font-weight:700;color:#111827">'
        f'{esc(title)}{count_badge}</h2>'
        f'{desc_html}'
        f'{body_html}'
        f'</div>'
    )


def _render_tab_nav(tab_defs: list) -> str:
    """Render the horizontal tab button bar."""
    buttons = ""
    for i, (tab_id, label, count, count_color, _) in enumerate(tab_defs):
        active_class = " active" if i == 0 else ""
        count_html = (
            f'<span style="background:{count_color};color:#fff;padding:1px 7px;'
            f'border-radius:10px;font-size:0.68rem;font-weight:700">{count}</span>'
        ) if count else ""
        buttons += (
            f'<button class="tab-btn{active_class}" data-tab="{tab_id}">'
            f'{esc(label)}{count_html}</button>'
        )
    return f'<div class="tab-nav">{buttons}</div>'


# ---------------------------------------------------------------------------
# Table + accordion helpers
# ---------------------------------------------------------------------------

def _table_wrap(headers: list, rows_html: str, col_widths: list = None, right_cols: set = None) -> str:
    """Scrollable table with standard column headers.

    col_widths  — optional list of CSS widths matching headers (e.g. ["10%","8%","auto","14%"])
    right_cols  — set of header names to right-align (header and cells should match)
    """
    right_cols = right_cols or set()
    th_base = (
        "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;"
        "background:#f9fafb;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
    )
    th_cells = "".join(
        f'<th style="{th_base};text-align:{"right" if h in right_cols else "left"}">{esc(h)}</th>'
        for h in headers
    )
    colgroup = ""
    if col_widths:
        colgroup = "<colgroup>" + "".join(f'<col style="width:{w}">' for w in col_widths) + "</colgroup>"
    return (
        f'<div style="overflow:auto;max-height:320px;margin-top:10px;'
        f'border:1px solid #e5e7eb;border-radius:6px">'
        f'<table style="width:100%;min-width:700px;border-collapse:collapse;'
        f'font-size:0.82rem;table-layout:fixed">'
        f'{colgroup}'
        f'<thead style="position:sticky;top:0;z-index:1"><tr>{th_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
    )


def _show_more_row(n_hidden: int, n_cols: int, td: str) -> str:
    """Return a <tr> with a 'Show N more findings' button that reveals .extra-row siblings."""
    onclick = (
        "var tb=this.closest('tbody');"
        "tb.querySelectorAll('.extra-row').forEach(function(r){r.style.display=''});"
        "this.closest('tr').style.display='none'"
    )
    btn_style = (
        "background:none;border:1px solid #d1d5db;border-radius:6px;"
        "padding:5px 16px;cursor:pointer;color:#6b7280;font-size:0.82em"
    )
    return (
        f'<tr class="show-more-row">'
        f'<td colspan="{n_cols}" style="{td};text-align:center;padding:10px">'
        f'<button onclick="{onclick}" style="{btn_style}">'
        f'Show {n_hidden} more findings &#9660;</button></td></tr>'
    )


def _accordion(title: str, count: int, sev: str, body_html: str, open_: bool = False) -> str:
    """Inner accordion item — a collapsible finding group within a section."""
    color  = SEV_COLOR.get(sev, "#374151")
    bg     = SEV_BG.get(sev, "#f9fafb")
    border = SEV_BORDER.get(sev, "#e5e7eb")
    count_pill = (
        f'<span class="dyn-count" style="background:{color};color:#fff;border-radius:10px;'
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
        f'<span class="chevron" style="margin-left:auto;color:#9ca3af;font-size:0.75rem;display:inline-block">▶</span>'
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
        for idx, issue in enumerate(items):
            detail = issue.get("detail", "")
            clean  = detail
            if clean.startswith("Row ") and ": " in clean:
                clean = clean.split(": ", 1)[1]
            elif clean.startswith("Rows ") and ": " in clean:
                clean = clean.split(": ", 1)[1]
            sev_i = issue.get("severity", sev)
            _du = esc((issue.get("user") or "").lower())
            _dp = esc((issue.get("project") or "").lower())
            extra = ' class="extra-row" style="display:none"' if idx >= 50 else ''
            rows_html += (
                f'<tr{extra} data-user="{_du}" data-project="{_dp}">'
                f'<td style="{td}">{badge(sev_i)}</td>'
                f'<td style="{td}">{esc(issue.get("user",""))}</td>'
                f'<td style="{td}">{esc(issue.get("date",""))}</td>'
                f'<td style="{td}">{esc(issue.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(clean or issue.get("brief",""))}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += _show_more_row(len(items) - 50, 5, td)

        table = _table_wrap(["Sev", "User", "Date", "Project", "Detail"], rows_html)
        body  = (_action_hint(action) if action else "") + _source_chips(sources) + table
        parts.append(_accordion(f"{check} — {label}", len(items), sev, body, open_=(i == 0)))

    # CHECK-13 (Hours accuracy)
    c13 = [i for i in issues if i["check"] == "CHECK-13"]
    if c13:
        rows_html = ""
        for idx, issue in enumerate(c13):
            detail = issue.get("detail", "")
            clean  = detail.split(": ", 1)[1] if ": " in detail else detail
            _du = esc((issue.get("user") or "").lower())
            _dp = esc((issue.get("project") or "").lower())
            extra = ' class="extra-row" style="display:none"' if idx >= 50 else ''
            rows_html += (
                f'<tr{extra} data-user="{_du}" data-project="{_dp}">'
                f'<td style="{td}">{esc(issue.get("user",""))}</td>'
                f'<td style="{td}">{esc(issue.get("date",""))}</td>'
                f'<td style="{td};color:#374151">{esc(clean or issue.get("brief",""))}</td>'
                f'</tr>'
            )
        if len(c13) > 50:
            rows_html += _show_more_row(len(c13) - 50, 3, td)
        table = _table_wrap(["User", "Date", "Detail"], rows_html)
        body  = _action_hint(CHECK_ACTIONS["CHECK-13"]) + _source_chips(CHECK_SOURCES["CHECK-13"]) + table
        parts.append(_accordion("CHECK-13 — Hours Field Accuracy", len(c13), "INFO", body))

    return "".join(parts)


def _render_leakage(leakage: dict, slack_signals: dict = None) -> str:
    findings = leakage.get("findings", [])
    if not findings:
        return '<p style="color:#6b7280;font-style:italic">No leakage signals detected.</p>'

    # Build a lookup of (user, date) → {text, channel} for unlogged_work enrichment
    slack_msg_lookup: dict = {}
    if slack_signals:
        for s in slack_signals.get("work_without_timesheet", []):
            slack_msg_lookup[(s.get("user", ""), s.get("date", ""))] = {
                "text":    s.get("text", ""),
                "channel": s.get("channel", ""),
            }

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

        # Per-type column layout
        # unlogged_work: project & impact both null — description already has channel+message
        # contract_hours_underbilling: monthly aggregate, no project
        no_project  = (ftype in ("contract_hours_underbilling", "unlogged_work"))
        no_impact   = (ftype == "unlogged_work")

        if ftype == "unlogged_work":
            headers    = ["User", "Date", "Project", "Slack Message"]
            col_widths = ["11%", "8%", "13%", "auto"]
        elif ftype == "contract_hours_underbilling":
            headers    = ["User", "Month", "Description", "Impact (USD)"]
            col_widths = ["11%", "8%", "auto", "13%"]
        else:
            headers    = ["User", "Date", "Project", "Description", "Impact (USD)"]
            col_widths = ["11%", "8%", "11%", "auto", "13%"]

        rows_html = ""
        for idx, f in enumerate(items):
            impact     = f.get("estimated_impact")
            impact_str = f"${impact:,.2f}" if impact else "—"
            date_val   = f.get("date", "") or ""
            month_val  = date_val[:7] if ftype == "contract_hours_underbilling" else date_val
            _du = esc((f.get("user") or "").lower())
            _dp = esc((f.get("project") or "").lower())
            extra = ' class="extra-row" style="display:none"' if idx >= 50 else ''
            if ftype == "unlogged_work":
                slack_info   = slack_msg_lookup.get((f.get("user", ""), f.get("date", "")), {})
                channel      = slack_info.get("channel", "")
                project_cell = f"#{channel}" if channel else "—"
                msg_cell     = slack_info.get("text", "") or f.get("description", "")
                rows_html += (
                    f'<tr{extra} data-user="{_du}" data-project="{_dp}">'
                    f'<td style="{td};font-weight:600">{esc(f.get("user",""))}</td>'
                    f'<td style="{td}">{esc(date_val)}</td>'
                    f'<td style="{td}">{esc(project_cell)}</td>'
                    f'<td style="{td};color:#374151">{esc(msg_cell)}</td>'
                    f'</tr>'
                )
            else:
                rows_html += (
                    f'<tr{extra} data-user="{_du}" data-project="{_dp}">'
                    f'<td style="{td};font-weight:600">{esc(f.get("user",""))}</td>'
                    f'<td style="{td}">{esc(month_val)}</td>'
                    + ("" if no_project else f'<td style="{td}">{esc(f.get("project","") or "")}</td>')
                    + f'<td style="{td};color:#374151">{esc(f.get("description",""))}</td>'
                    + ("" if no_impact else f'<td style="{td};text-align:right;font-weight:600;color:#dc2626">{impact_str}</td>')
                    + f'</tr>'
                )
        if len(items) > 50:
            rows_html += _show_more_row(len(items) - 50, len(headers), td)

        title_str = label
        if total_impact:
            title_str += f" — ${total_impact:,.0f} at risk"

        table = _table_wrap(headers, rows_html, col_widths=col_widths, right_cols={"Impact (USD)"})
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
        for idx, f in enumerate(items):
            _du = esc((f.get("user") or "").lower())
            _dp = esc((f.get("project") or "").lower())
            extra = ' class="extra-row" style="display:none"' if idx >= 50 else ''
            rows_html += (
                f'<tr{extra} data-user="{_du}" data-project="{_dp}">'
                f'<td style="{td};font-weight:600">{esc(f.get("user",""))}</td>'
                f'<td style="{td}">{esc(f.get("date","") or "")}</td>'
                f'<td style="{td}">{esc(f.get("project","") or "")}</td>'
                f'<td style="{td};color:#374151">{esc(f.get("description",""))}</td>'
                f'</tr>'
            )
        if len(items) > 50:
            rows_html += _show_more_row(len(items) - 50, 4, td)

        table = _table_wrap(["User", "Date", "Project", "Description"], rows_html,
                            col_widths=["15%", "9%", "14%", "62%"])
        body  = _action_hint(action) + _source_chips(sources) + table
        parts.append(_accordion(label, len(items), sev, body, open_=(i == 0)))

    return "".join(parts)


def _render_slack_unlogged(slack: dict) -> str:
    unlogged = slack.get("work_without_timesheet", [])
    if not unlogged:
        return '<p style="color:#6b7280;font-style:italic">No unlogged Slack work signals found.</p>'

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    rows_html = ""
    for idx, s in enumerate(unlogged):
        channel     = s.get("channel", "")
        channel_str = f"#{channel}" if channel else "—"
        _du = esc((s.get("user") or "").lower())
        extra = ' class="extra-row" style="display:none"' if idx >= 60 else ''
        rows_html += (
            f'<tr{extra} data-user="{_du}">'
            f'<td style="{td};font-weight:600">{esc(s["user"])}</td>'
            f'<td style="{td}">{esc(s["date"])}</td>'
            f'<td style="{td};color:#6b7280">{esc(channel_str)}</td>'
            f'<td style="{td};color:#374151;font-style:italic">{esc(s["text"][:200])}</td>'
            f'</tr>'
        )
    if len(unlogged) > 60:
        rows_html += _show_more_row(len(unlogged) - 60, 4, td)

    table = _table_wrap(["User", "Date", "Channel", "Slack Message"], rows_html)
    body  = (
        _action_hint("Chase a timesheet entry from each user for the listed date.")
        + _source_chips(["slack_activity.csv", "kimai_timesheets.csv (entry missing)"])
        + table
    )
    return _accordion(f"Unlogged Work Signals", len(unlogged), "WARNING", body, open_=True)


def _render_invoice(invoice: dict) -> str:
    lines     = invoice.get("invoice_lines", [])
    subtotals = invoice.get("project_subtotals", {})
    warnings  = invoice.get("warnings", [])
    grand     = invoice.get("grand_total", 0)
    total_h   = invoice.get("billable_hours_total", 0)

    if not lines:
        return '<p style="color:#6b7280;font-style:italic">No billable work units found.</p>'

    FLAG_LEGEND = {
        "rate_fallback": (
            "#d97706", "#fffbeb", "#fde68a",
            "No contract rate found — timesheet rate used. Verify before sending."
        ),
        "role_mismatch": (
            "#dc2626", "#fef2f2", "#fca5a5",
            "User not listed in the SOW team roster. Needs approval before billing."
        ),
        "name_ambiguous": (
            "#7c3aed", "#f5f3ff", "#ddd6fe",
            "First name shared by multiple users — confirm correct person is being billed."
        ),
        "name_variant": (
            "#b45309", "#fffbeb", "#fde68a",
            "Bare first name may be a variant of another user — risk of double-billing or misattribution."
        ),
    }

    legend_html = (
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">'
        + "".join(
            f'<div style="display:flex;align-items:center;gap:8px;padding:6px 12px;'
            f'background:{bg};border:1px solid {border};border-radius:6px">'
            f'<span style="background:#fee2e2;color:{color};padding:1px 7px;'
            f'border-radius:3px;font-size:0.7rem;font-weight:700;white-space:nowrap">{flag}</span>'
            f'<span style="font-size:0.78rem;color:#374151">{meaning}</span>'
            f'</div>'
            for flag, (color, bg, border, meaning) in FLAG_LEGEND.items()
        )
        + f'</div>'
    )

    # Build per-project warning lookup
    proj_warnings: dict = defaultdict(list)
    for w in warnings:
        assigned = False
        for proj_key in [l["project"] for l in lines]:
            if proj_key.lower() in w.lower() or w.lower() in proj_key.lower():
                proj_warnings[proj_key].append(w)
                assigned = True
                break
        if not assigned:
            proj_warnings["__global__"].append(w)

    global_warnings_html = "".join(
        f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:4px;'
        f'padding:6px 12px;margin-bottom:6px;font-size:0.8rem;color:#78350f">'
        f'&#9888; {esc(w)}</div>'
        for w in proj_warnings.get("__global__", [])
    )

    by_proj = defaultdict(list)
    for l in lines:
        by_proj[l["project"]].append(l)

    # Fixed column widths — same across all project tables for consistent alignment
    COL_WIDTHS  = ["28%", "22%", "10%", "13%", "12%", "15%"]
    COL_HEADERS = ["User", "Role", "Hours", "Rate ($/hr)", "Amount", "Flags"]

    def _col_group() -> str:
        return "".join(f'<col style="width:{w}">' for w in COL_WIDTHS)

    td       = "padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top"
    th_base  = (
        "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;"
        "color:#6b7280;border-bottom:2px solid #e5e7eb;background:#f9fafb;"
        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
    )
    th_left  = th_base + ";text-align:left"
    th_right = th_base + ";text-align:right"

    parts = [legend_html, global_warnings_html]
    for proj in sorted(by_proj.keys()):
        proj_lines = by_proj[proj]
        proj_total = subtotals.get(proj, 0)
        flagged    = sum(1 for l in proj_lines if l.get("flags"))

        # Per-project warnings inside each accordion
        proj_warn_html = "".join(
            f'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:4px;'
            f'padding:6px 12px;margin-bottom:6px;font-size:0.8rem;color:#78350f">'
            f'&#9888; {esc(w)}</div>'
            for w in proj_warnings.get(proj, [])
        )

        rows_html = ""
        for line in proj_lines:
            flags = line.get("flags", [])
            flag_html = (
                "<br>".join(
                    f'<span style="display:inline-block;background:#fee2e2;color:#dc2626;'
                    f'padding:1px 6px;border-radius:3px;font-size:0.68rem;font-weight:600;'
                    f'margin-bottom:2px">{esc(fl)}</span>'
                    for fl in flags
                ) if flags else ""
            )
            _du = esc((line.get("user") or "").lower())
            _dp = esc(proj.lower())
            rows_html += (
                f'<tr data-user="{_du}" data-project="{_dp}">'
                f'<td style="{td};font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(line["user"])}</td>'
                f'<td style="{td};color:#6b7280;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(line.get("role",""))}</td>'
                f'<td style="{td};text-align:right">{line["hours"]:.2f}</td>'
                f'<td style="{td};text-align:right">{line["rate"]:.2f}</td>'
                f'<td style="{td};text-align:right;font-weight:700;color:#16a34a">${line["amount"]:,.2f}</td>'
                f'<td style="{td}">{flag_html}</td>'
                f'</tr>'
            )

        th_cells = (
            f'<th style="{th_left}">{COL_HEADERS[0]}</th>'
            f'<th style="{th_left}">{COL_HEADERS[1]}</th>'
            f'<th style="{th_right}">{COL_HEADERS[2]}</th>'
            f'<th style="{th_right}">{COL_HEADERS[3]}</th>'
            f'<th style="{th_right}">{COL_HEADERS[4]}</th>'
            f'<th style="{th_left}">{COL_HEADERS[5]}</th>'
        )

        table_html = (
            f'<div style="overflow:auto;max-height:280px;border:1px solid #e5e7eb;border-radius:6px">'
            f'<table style="width:100%;border-collapse:collapse;font-size:0.82rem;table-layout:fixed">'
            f'<colgroup>{_col_group()}</colgroup>'
            f'<thead style="position:sticky;top:0;z-index:1"><tr>{th_cells}</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table></div>'
        )

        flag_note = (
            f'<span style="font-size:0.72rem;color:#dc2626;margin-left:6px">'
            f'⚠ {flagged} flagged</span>'
        ) if flagged else ""

        parts.append(
            f'<details data-project="{esc(proj.lower())}" style="border:1px solid #e5e7eb;border-radius:6px;'
            f'margin-bottom:8px;background:#fff">'
            f'<summary style="cursor:pointer;list-style:none;padding:12px 16px;'
            f'display:flex;align-items:center;gap:6px;user-select:none">'
            f'<span class="chevron" style="color:#9ca3af;font-size:0.75rem;display:inline-block">▶</span>'
            f'<span style="font-weight:600;font-size:0.87rem;color:#111827">{esc(proj)}</span>'
            f'{flag_note}'
            f'<span style="margin-left:auto;font-weight:700;color:#16a34a;font-size:0.9rem">'
            f'${proj_total:,.2f}</span>'
            f'</summary>'
            f'<div style="padding:0 14px 14px">{proj_warn_html}{table_html}</div>'
            f'</details>'
        )

    # Grand total footer
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
    contract_model:    dict = None,
) -> str:
    # Build SOW caps: monthly_cap_hours and monthly_value per project
    sow_projects: dict = {}
    if contract_model:
        for pname, pdata in contract_model.get("projects", {}).items():
            sow_projects[pname] = {
                "monthly_cap_hours": pdata.get("monthly_cap_hours") or 0,
                "monthly_value":     pdata.get("monthly_value") or "",
            }

    all_projs = sorted(set(proj_budget_hours) | set(proj_actual_hours))
    if not all_projs:
        return '<p style="color:#6b7280;font-style:italic">No project budget data found (pm_projects.csv / SOW).</p>'
    td = "padding:8px 12px;border-bottom:1px solid #f3f4f6;vertical-align:middle"

    rows_html = ""
    for proj in all_projs:
        bh  = proj_budget_hours.get(proj, 0)
        ah  = proj_actual_hours.get(proj, 0)
        bc  = proj_budget_cost.get(proj, 0)
        ac  = proj_actual_cost.get(proj, 0)

        # Fall back to SOW data when pm_projects.csv has no budget
        sow = sow_projects.get(proj, {})
        sow_cap_h = sow.get("monthly_cap_hours", 0) or 0
        sow_value = sow.get("monthly_value", "") or ""
        bh_source = "csv"
        if not bh and sow_cap_h:
            bh = sow_cap_h
            bh_source = "sow"

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

        # Budget hours cell — badge SOW-sourced values
        if bh_source == "sow":
            bh_cell = (
                f'{bh:,.0f}h '
                f'<span style="background:#7c3aed;color:#fff;border-radius:3px;'
                f'padding:0 5px;font-size:0.65rem;font-weight:700" '
                f'title="Sourced from SOW monthly_cap_hours">SOW</span>'
            )
        else:
            bh_cell = f'{bh:,.0f}h' if bh else "—"

        # Budget cost cell — show SOW monthly_value as reference if no csv cost
        if not bc and sow_value:
            bc_cell = (
                f'<span style="color:#6b7280;font-size:0.78rem" '
                f'title="Monthly contract value from SOW">{esc(sow_value)}</span>'
            )
        else:
            bc_cell = f'${bc:,.0f}' if bc else "—"

        _dp = esc(proj.lower())
        rows_html += (
            f'<tr style="{row_bg}" data-project="{_dp}">'
            f'<td style="{td};font-weight:600">{esc(proj)}</td>'
            f'<td style="{td};text-align:center">{status_html}</td>'
            f'<td style="{td};text-align:right">{ah:,.1f}h</td>'
            f'<td style="{td};text-align:right">{bh_cell}</td>'
            f'<td style="{td};text-align:right">{h_delta_str}</td>'
            f'<td style="{td};text-align:right">${ac:,.0f}</td>'
            f'<td style="{td};text-align:right">{bc_cell}</td>'
            f'<td style="{td};text-align:right">{c_delta_str}</td>'
            f'</tr>'
        )

    th_base = (
        "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;"
        "color:#6b7280;border-bottom:2px solid #e5e7eb;background:#f9fafb;white-space:nowrap"
    )
    budget_headers = [
        ("Project",     "30%", "text-align:left",   "Project name from pm_projects.csv"),
        ("Status",      "10%", "text-align:center",  "Budget utilisation: OVER >100%, NEAR 90–100%, % used <90%. 'no budget' means no cap is defined in pm_projects.csv."),
        ("Actual Hrs",  "10%", "text-align:right",   "Total hours logged in timesheets for this project so far."),
        ("Budget Hrs",  "10%", "text-align:right",   "Contracted hour cap from the SOW / pm_projects.csv (budget_hours column)."),
        ("Δ Hours",     "10%", "text-align:right",   "Actual minus Budget hours. Red (+) = over budget. Green (−) = under budget."),
        ("Actual Cost", "10%", "text-align:right",   "Actual hours × employee rates — what has been spent so far."),
        ("Budget Cost", "10%", "text-align:right",   "Contracted cost ceiling from the SOW / pm_projects.csv (budget_cost column)."),
        ("Δ Cost",      "10%", "text-align:right",   "Actual minus Budget cost in dollars. Red (+) = over budget. Green (−) = under budget."),
    ]
    col_group = "".join(f'<col style="width:{w}">' for _, w, _, _t in budget_headers)
    th_cells  = "".join(
        f'<th style="{th_base};{align}">'
        f'{lbl}<span class="col-tip" data-tip="{esc(tip)}">?</span>'
        f'</th>'
        for lbl, _, align, tip in budget_headers
    )
    table = (
        f'<div style="overflow:auto;max-height:320px;margin-top:10px;'
        f'border:1px solid #e5e7eb;border-radius:6px">'
        f'<table style="width:100%;min-width:800px;border-collapse:collapse;'
        f'font-size:0.82rem;table-layout:fixed">'
        f'<colgroup>{col_group}</colgroup>'
        f'<thead style="position:sticky;top:0;z-index:1"><tr>{th_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
    )
    src_chips = ["pm_projects.csv (budget_hours, budget_cost)", "kimai_timesheets.csv (actuals)"]
    if sow_projects:
        src_chips.append("SOW documents (monthly_cap_hours, monthly_value)")
    source = _source_chips(src_chips)
    return table + source


_DQ_FLAG_SEVERITY = {
    "invalid_timestamp":     "CRITICAL",
    "hours_mismatch":        "WARNING",
    "missing_project":       "WARNING",
    "missing_activity":      "WARNING",
    "public_holiday_entry":  "WARNING",
    "weekend_entry":         "INFO",
    "late_submission":       "INFO",
    "missing_description":   "INFO",
}


def _render_all_issues_table(
    issues: list,
    work_units_data,
    leakage_findings=None,
    compliance_findings=None,
) -> str:
    """
    Flat table of every timesheet issue in one place:
      - rule-based check findings (CHECK-1 … CHECK-N)
      - compliance agent findings
      - leakage agent findings
      - data quality issues from the normalisation agent
    Sorted CRITICAL → WARNING → INFO, then by date.
    Includes inline filters (severity, check type, user, project) and row background colors.
    """
    from audit.checks import LABELS

    SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}

    rows: list[dict] = []
    # list of (check_key, display_label) — key matches data-check on rows, display shown in dropdown
    check_types: list[tuple[str, str]] = []
    _check_type_keys: set[str] = set()

    def _add_check_type(key: str, display: str) -> None:
        """Register a filter option; key must match what goes in data-check."""
        if key not in _check_type_keys:
            check_types.append((key, display))
            _check_type_keys.add(key)

    # ---- Rule-based check issues ----
    for issue in issues:
        check = issue.get("check", "")
        label = LABELS.get(check, check)
        source = f'{check} — {label}'
        detail = issue.get("detail", "")
        if ": " in detail:
            detail = detail.split(": ", 1)[1]
        rows.append({
            "severity": issue.get("severity", "INFO"),
            "source":   source,
            "check_key": check,
            "user":     issue.get("user", ""),
            "date":     issue.get("date", "") or "",
            "project":  issue.get("project", "") or "",
            "detail":   detail or issue.get("brief", ""),
        })
        # Display just the label (no "CHECK-N —" prefix)
        _add_check_type(check.lower(), label)

    # ---- Compliance agent findings ----
    if compliance_findings:
        for finding in compliance_findings.get("findings", []):
            ftype   = finding.get("type", "")
            source  = ftype.replace("_", " ").title()
            rows.append({
                "severity": finding.get("severity", "CRITICAL"),
                "source":   source,
                "check_key": ftype,
                "user":     finding.get("user", ""),
                "date":     finding.get("date", "") or "",
                "project":  finding.get("project", "") or "",
                "detail":   finding.get("description", ""),
            })
            _add_check_type(ftype.lower(), source)

    # ---- Leakage agent findings ----
    if leakage_findings:
        for finding in leakage_findings.get("findings", []):
            ftype  = finding.get("type", "")
            source = ftype.replace("_", " ").title()
            rows.append({
                "severity": finding.get("severity", "WARNING"),
                "source":   source,
                "check_key": ftype,
                "user":     finding.get("user", ""),
                "date":     finding.get("date", "") or "",
                "project":  finding.get("project", "") or "",
                "detail":   finding.get("description", ""),
            })
            _add_check_type(ftype.lower(), source)

    # ---- Data quality issues from normalisation agent ----
    if work_units_data:
        for issue in work_units_data.get("data_quality_issues", []):
            flag   = issue.get("flag", "")
            source = flag.replace("_", " ").title()
            sev    = issue.get("severity") or _DQ_FLAG_SEVERITY.get(flag, "INFO")
            rows.append({
                "severity": sev,
                "source":   source,
                "check_key": source,
                "user":     issue.get("user", ""),
                "date":     issue.get("date", "") or "",
                "project":  issue.get("project", "") or "",
                "detail":   issue.get("description", ""),
            })
            _add_check_type(source.lower(), source)

    if not rows:
        return '<p style="color:#6b7280;font-style:italic">No issues found.</p>'

    rows.sort(key=lambda r: (SEV_ORDER.get(r["severity"], 2), r["date"]))
    total = min(len(rows), 500)

    # ---- Inline filter bar ----
    sel_style = (
        "padding:4px 8px;border:1px solid #d1d5db;border-radius:5px;"
        "font-size:0.78rem;background:#fff;color:#111827;cursor:pointer"
    )
    inp_style = (
        "padding:4px 8px;border:1px solid #d1d5db;border-radius:5px;"
        "font-size:0.78rem;background:#fff;color:#111827;width:110px"
    )
    btn_style = (
        "padding:4px 10px;border:1px solid #d1d5db;border-radius:5px;"
        "font-size:0.78rem;background:#f3f4f6;color:#374151;cursor:pointer"
    )
    check_opts = "".join(
        f'<option value="{esc(key)}">{esc(display)}</option>'
        for key, display in sorted(check_types, key=lambda x: x[1])
    )
    filter_bar = (
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;'
        f'margin-bottom:10px;padding:8px 12px;background:#f9fafb;'
        f'border:1px solid #e5e7eb;border-radius:6px">'
        f'<select id="ai-sev" style="{sel_style}">'
        f'<option value="">All Severities</option>'
        f'<option value="critical">CRITICAL</option>'
        f'<option value="warning">WARNING</option>'
        f'<option value="info">INFO</option>'
        f'</select>'
        f'<select id="ai-check" style="{sel_style}">'
        f'<option value="">All Check Types</option>'
        f'{check_opts}'
        f'</select>'
        f'<input id="ai-user" placeholder="User…" style="{inp_style}">'
        f'<input id="ai-proj" placeholder="Project…" style="{inp_style}">'
        f'<button id="ai-clear" style="{btn_style}">Clear</button>'
        f'<span style="margin-left:4px;font-size:0.78rem;color:#6b7280">'
        f'Showing <b id="ai-count">{total}</b> of {len(rows):,} issues'
        f'</span>'
        f'</div>'
    )

    # ---- Table rows ----
    th_style = (
        "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;"
        "text-align:left;background:#f9fafb;overflow:hidden;text-overflow:ellipsis;"
        "white-space:nowrap"
    )
    headers = ["Severity", "Check / Type", "User", "Date", "Project", "Issue"]
    th_cells = "".join(f'<th style="{th_style}">{esc(h)}</th>' for h in headers)

    rows_html = ""
    for r in rows[:500]:
        sev  = r["severity"]
        bg   = SEV_BG.get(sev, "#fff")
        _ds  = esc(sev.lower())
        _dck = esc(r["check_key"].lower())
        _du  = esc(r["user"].lower())
        _dp  = esc(r["project"].lower())
        td   = f"padding:7px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top;background:{bg}"
        rows_html += (
            f'<tr data-severity="{_ds}" data-check="{_dck}" data-user="{_du}" data-project="{_dp}">'
            f'<td style="{td}">{badge(sev)}</td>'
            f'<td style="{td};color:#6b7280;font-size:0.78rem;white-space:normal">{esc(r["source"])}</td>'
            f'<td style="{td};font-weight:600">{esc(r["user"])}</td>'
            f'<td style="{td};white-space:nowrap">{esc(r["date"])}</td>'
            f'<td style="{td}">{esc(r["project"])}</td>'
            f'<td style="{td};white-space:normal;color:#374151">{esc(r["detail"])}</td>'
            f'</tr>'
        )
    if len(rows) > 500:
        rows_html += (
            f'<tr class="ai-trunc-row"><td colspan="6" style="padding:7px 12px;color:#9ca3af;font-style:italic">'
            f'… and {len(rows)-500} more issues (showing first 500).</td></tr>'
        )

    table_html = (
        f'<div style="overflow:auto;max-height:480px;border:1px solid #e5e7eb;border-radius:6px">'
        f'<table id="ai-issues-table" style="width:100%;min-width:780px;border-collapse:collapse;font-size:0.82rem">'
        f'<thead style="position:sticky;top:0;z-index:1"><tr>{th_cells}</tr></thead>'
        f'<tbody id="ai-issues-tbody">{rows_html}</tbody>'
        f'</table></div>'
    )

    chips = _source_chips(["kimai_timesheets.csv", "normalisation agent (work units)"])

    # ---- Inline JS for this table ----
    filter_js = f"""<script>
(function() {{
  var sevSel   = document.getElementById('ai-sev');
  var checkSel = document.getElementById('ai-check');
  var userInp  = document.getElementById('ai-user');
  var projInp  = document.getElementById('ai-proj');
  var clearBtn = document.getElementById('ai-clear');
  var countEl  = document.getElementById('ai-count');
  if (!sevSel) return;

  function applyFilters() {{
    var sev   = sevSel.value;
    var chk   = checkSel.value;
    var usr   = userInp.value.toLowerCase().trim();
    var prj   = projInp.value.toLowerCase().trim();
    var visible = 0;
    document.querySelectorAll('#ai-issues-tbody tr:not(.ai-trunc-row)').forEach(function(tr) {{
      var ok = true;
      if (sev && tr.dataset.severity !== sev) ok = false;
      if (chk && tr.dataset.check.indexOf(chk) === -1) ok = false;
      if (usr && tr.dataset.user.indexOf(usr) === -1) ok = false;
      if (prj && tr.dataset.project.indexOf(prj) === -1) ok = false;
      tr.style.display = ok ? '' : 'none';
      if (ok) visible++;
    }});
    if (countEl) countEl.textContent = visible;
    var truncRow = document.querySelector('#ai-issues-tbody .ai-trunc-row');
    if (truncRow) truncRow.style.display = (sev || chk || usr || prj) ? 'none' : '';
  }}

  sevSel.addEventListener('change', applyFilters);
  checkSel.addEventListener('change', applyFilters);
  userInp.addEventListener('input', applyFilters);
  projInp.addEventListener('input', applyFilters);
  if (clearBtn) {{
    clearBtn.addEventListener('click', function() {{
      sevSel.value = ''; checkSel.value = '';
      userInp.value = ''; projInp.value = '';
      applyFilters();
    }});
  }}
}})();
</script>"""

    return chips + filter_bar + table_html + filter_js


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
        "late_submission",
    ]
    FLAG_SOURCES = {
        "late_submission": ["kimai_timesheets.csv (submitted_at)", "kimai_timesheets.csv (date)"],
    }
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
        sources = FLAG_SOURCES.get(flag, ["kimai_timesheets.csv"])
        body  = _source_chips(sources) + table
        parts.append(_accordion(label, len(items), "INFO", body, open_=(i == 0)))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Executive Intelligence Panel (AI-generated insights)
# ---------------------------------------------------------------------------

def _render_executive_insights(insights: dict) -> str:
    """Render the AI-generated Intelligence Panel card."""
    if not insights:
        return ""

    card_style = (
        "background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:16px;"
        "border:1px solid #e5e7eb;box-shadow:0 1px 4px rgba(0,0,0,.06)"
    )
    header_style = (
        "margin:0 0 16px;font-size:1rem;font-weight:800;display:flex;"
        "align-items:center;gap:10px"
    )
    badge = (
        '<span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;'
        'border-radius:8px;padding:2px 10px;font-size:0.72rem;font-weight:700;'
        'letter-spacing:0.03em">AI</span>'
    )

    sections_html = ""

    # ── Top Revenue Risks ──────────────────────────────────────────────────
    risks = insights.get("top_revenue_risks", [])
    if risks:
        rows = ""
        for r in risks[:3]:
            impact = r.get("impact_usd")
            impact_badge = (
                f'<span style="float:right;background:#fef2f2;color:#dc2626;'
                f'border-radius:8px;padding:1px 8px;font-size:0.72rem;font-weight:700">'
                f'${impact:,.0f}</span>'
            ) if impact else ""
            rows += (
                f'<div style="padding:10px 12px;border-radius:7px;margin-bottom:6px;'
                f'background:#fef9f9;border-left:3px solid #dc2626">'
                f'{impact_badge}'
                f'<div style="font-weight:700;font-size:0.82rem;color:#111827;margin-bottom:2px">'
                f'#{r.get("rank","")} {esc(r.get("title",""))}</div>'
                f'<div style="font-size:0.78rem;color:#374151">{esc(r.get("description",""))}</div>'
                f'</div>'
            )
        sections_html += (
            f'<div style="margin-bottom:18px">'
            f'<div style="font-weight:700;font-size:0.78rem;color:#dc2626;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">'
            f'Top Revenue Risks</div>{rows}</div>'
        )

    # ── Top Compliance Blockers ────────────────────────────────────────────
    blockers = insights.get("top_compliance_blockers", [])
    if blockers:
        rows = ""
        for b in blockers[:3]:
            sev = b.get("severity", "WARNING")
            sev_color = "#dc2626" if sev == "CRITICAL" else "#d97706"
            sev_bg    = "#fef2f2" if sev == "CRITICAL" else "#fffbeb"
            sev_badge = (
                f'<span style="float:right;background:{sev_bg};color:{sev_color};'
                f'border-radius:8px;padding:1px 8px;font-size:0.70rem;font-weight:700">{sev}</span>'
            )
            action = b.get("action", "")
            rows += (
                f'<div style="padding:10px 12px;border-radius:7px;margin-bottom:6px;'
                f'background:#fffdf5;border-left:3px solid {sev_color}">'
                f'{sev_badge}'
                f'<div style="font-weight:700;font-size:0.82rem;color:#111827;margin-bottom:2px">'
                f'#{b.get("rank","")} {esc(b.get("title",""))}</div>'
                f'<div style="font-size:0.78rem;color:#374151;margin-bottom:4px">{esc(b.get("description",""))}</div>'
                + (f'<div style="font-size:0.74rem;color:#6b7280"><b>Action:</b> {esc(action)}</div>' if action else "")
                + f'</div>'
            )
        sections_html += (
            f'<div style="margin-bottom:18px">'
            f'<div style="font-weight:700;font-size:0.78rem;color:#d97706;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">'
            f'Top Compliance Blockers</div>{rows}</div>'
        )

    # ── Quick Wins ─────────────────────────────────────────────────────────
    qw = insights.get("quick_wins", {})
    act_now     = qw.get("act_now", [])
    recover_fast = qw.get("recover_fast", [])
    if act_now or recover_fast:
        cols = ""
        for label, color, items in [
            ("Act Now",      "#16a34a", act_now),
            ("Recover Fast", "#2563eb", recover_fast),
        ]:
            if not items:
                continue
            item_html = "".join(
                f'<div style="padding:8px 10px;border-radius:6px;margin-bottom:5px;'
                f'background:#f0fdf4 if "{color}"=="#16a34a" else #eff6ff;'
                f'border-left:3px solid {color}">'
                f'<div style="font-weight:700;font-size:0.80rem;color:#111827">{esc(it.get("title",""))}</div>'
                f'<div style="font-size:0.75rem;color:#374151">{esc(it.get("description",""))}</div>'
                f'</div>'
                for it in items
            )
            bg = "#f0fdf4" if color == "#16a34a" else "#eff6ff"
            item_html = "".join(
                f'<div style="padding:8px 10px;border-radius:6px;margin-bottom:5px;'
                f'background:{bg};border-left:3px solid {color}">'
                f'<div style="font-weight:700;font-size:0.80rem;color:#111827">{esc(it.get("title",""))}</div>'
                f'<div style="font-size:0.75rem;color:#374151">{esc(it.get("description",""))}</div>'
                f'</div>'
                for it in items
            )
            cols += (
                f'<div style="flex:1;min-width:200px">'
                f'<div style="font-weight:700;font-size:0.75rem;color:{color};'
                f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:7px">{label}</div>'
                f'{item_html}</div>'
            )
        sections_html += (
            f'<div style="margin-bottom:18px">'
            f'<div style="font-weight:700;font-size:0.78rem;color:#059669;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">'
            f'Quick Wins</div>'
            f'<div style="display:flex;gap:14px;flex-wrap:wrap">{cols}</div>'
            f'</div>'
        )

    # ── Critical Human Review ──────────────────────────────────────────────
    reviews = insights.get("critical_human_review", [])
    if reviews:
        rows = ""
        for rv in reviews:
            reason = rv.get("reason", "")
            rows += (
                f'<div style="padding:10px 12px;border-radius:7px;margin-bottom:6px;'
                f'background:#f5f3ff;border-left:3px solid #7c3aed">'
                f'<div style="font-weight:700;font-size:0.82rem;color:#111827;margin-bottom:2px">'
                f'{esc(rv.get("title",""))}</div>'
                f'<div style="font-size:0.78rem;color:#374151;margin-bottom:4px">{esc(rv.get("description",""))}</div>'
                + (f'<div style="font-size:0.74rem;color:#7c3aed"><b>Why human:</b> {esc(reason)}</div>' if reason else "")
                + f'</div>'
            )
        sections_html += (
            f'<div style="margin-bottom:6px">'
            f'<div style="font-weight:700;font-size:0.78rem;color:#7c3aed;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">'
            f'Critical Issues Requiring Human Review</div>{rows}</div>'
        )

    if not sections_html:
        return ""

    return (
        f'<div style="{card_style}">'
        f'<details>'
        f'<summary style="cursor:pointer;list-style:none;display:flex;align-items:center;'
        f'justify-content:space-between;padding:0;user-select:none">'
        f'<h2 style="{header_style}">Intelligence Panel {badge}</h2>'
        f'<span class="chevron" style="font-size:0.75rem;color:#9ca3af;display:inline-block">▶</span>'
        f'</summary>'
        f'<div style="margin-top:16px">{sections_html}</div>'
        f'</details>'
        f'</div>'
    )


def _synthesize_ai_digest(agent_summaries: dict, out_dir: str) -> dict:
    """
    Load the AI digest produced by the Digest Agent (audit_agent_sdk.py Phase 6).
    The digest is written to {out_dir}/agent_state/ai_digest.json by the pipeline.
    Returns an empty dict if the file is absent or malformed.
    """
    import json as _json

    cache_path = os.path.join(out_dir, "agent_state", "ai_digest.json")

    if os.path.exists(cache_path):
        try:
            with open(cache_path) as _f:
                digest = _json.load(_f)
            if all(k in digest for k in ("revenue_at_risk", "compliance_blockers",
                                         "invoice_status", "priority_actions")):
                return digest
        except Exception:
            pass

    return {}


def _render_ai_digest(digest: dict) -> str:
    """Render the Claude-synthesized digest as clean cards."""
    if not digest:
        return ""

    ai_badge = (
        '<span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;'
        'border-radius:8px;padding:2px 8px;font-size:0.68rem;font-weight:700;'
        'letter-spacing:0.03em;vertical-align:middle">AI</span>'
    )

    def _metric_card(title: str, accent: str, icon: str, headline: str, points: list) -> str:
        pts_html = "".join(
            f'<li style="font-size:0.82rem;color:#374151;margin-bottom:4px;padding-left:4px">{esc(p)}</li>'
            for p in points
        )
        list_html = f'<ul style="margin:8px 0 0 16px;padding:0">{pts_html}</ul>' if pts_html else ""
        return (
            f'<div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid {accent};'
            f'border-radius:8px;padding:14px 16px;margin-bottom:12px">'
            f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:{accent};margin-bottom:6px">{icon} {esc(title)}</div>'
            f'<div style="font-size:0.88rem;font-weight:600;color:#111827;margin-bottom:4px">{esc(headline)}</div>'
            f'{list_html}'
            f'</div>'
        )

    html_parts = [
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">'
        f'<div style="font-size:0.85rem;font-weight:700;color:#111827">Executive Digest</div>'
        f'{ai_badge}'
        f'<div style="font-size:0.75rem;color:#9ca3af;margin-left:4px">AI-generated synthesis</div>'
        f'</div>'
    ]

    rev = digest.get("revenue_at_risk", {})
    if rev:
        html_parts.append(_metric_card(
            "Revenue at Risk", "#dc2626", "⚠️",
            rev.get("headline", ""), rev.get("points", [])
        ))

    comp = digest.get("compliance_blockers", {})
    if comp:
        html_parts.append(_metric_card(
            "Compliance Blockers", "#d97706", "🚫",
            comp.get("headline", ""), comp.get("points", [])
        ))

    inv = digest.get("invoice_status", {})
    if inv:
        html_parts.append(_metric_card(
            "Invoice Status", "#16a34a", "🧾",
            inv.get("headline", ""), inv.get("points", [])
        ))

    actions = digest.get("priority_actions", [])
    if actions:
        items_html = "".join(
            f'<div style="display:flex;gap:8px;align-items:baseline;margin-bottom:6px">'
            f'<span style="background:#2563eb;color:#fff;border-radius:50%;min-width:18px;height:18px;'
            f'display:inline-flex;align-items:center;justify-content:center;font-size:0.65rem;font-weight:700">{i+1}</span>'
            f'<span style="font-size:0.82rem;color:#374151">{esc(a)}</span>'
            f'</div>'
            for i, a in enumerate(actions[:5])
        )
        html_parts.append(
            f'<div style="background:#f8faff;border:1px solid #e0e7ff;border-radius:8px;padding:14px 16px;margin-bottom:12px">'
            f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#2563eb;margin-bottom:10px">Priority Actions</div>'
            f'{items_html}'
            f'</div>'
        )

    return "".join(html_parts)


def _md_to_html(text: str) -> str:
    """Convert simple markdown (headers, bullets, bold) to HTML, stripping agent preamble."""
    import re as _re
    # Strip everything before the first ## heading (agent preamble like "I'll run...")
    m = _re.search(r'^##\s', text, _re.MULTILINE)
    if m:
        text = text[m.start():]

    lines = text.split("\n")
    parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if in_list:
                parts.append("</ul>"); in_list = False
            content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc(stripped[4:]))
            parts.append(f'<div style="font-size:0.82rem;font-weight:700;color:#374151;margin:12px 0 4px">{content}</div>')
        elif stripped.startswith("## "):
            if in_list:
                parts.append("</ul>"); in_list = False
            content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc(stripped[3:]))
            parts.append(f'<div style="font-size:0.88rem;font-weight:700;color:#111827;margin:14px 0 6px">{content}</div>')
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                parts.append('<ul style="margin:4px 0 4px 16px;padding:0">'); in_list = True
            bullet = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc(stripped[2:]))
            parts.append(f'<li style="font-size:0.82rem;color:#374151;margin-bottom:2px">{bullet}</li>')
        elif stripped.startswith("| "):
            # table — skip for now (too complex to render cleanly)
            if in_list:
                parts.append("</ul>"); in_list = False
        elif stripped == "" or stripped == "---":
            if in_list:
                parts.append("</ul>"); in_list = False
        else:
            if in_list:
                parts.append("</ul>"); in_list = False
            para = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc(stripped))
            parts.append(f'<p style="margin:4px 0;font-size:0.82rem;color:#374151">{para}</p>')

    if in_list:
        parts.append("</ul>")
    return "".join(parts)


def _summary_card(title: str, icon: str, accent: str, body_html: str, open_: bool = False) -> str:
    open_attr = " open" if open_ else ""
    return (
        f'<div class="card" style="margin-bottom:12px">'
        f'<details{open_attr}>'
        f'<summary style="cursor:pointer;list-style:none;display:flex;align-items:center;'
        f'justify-content:space-between;padding:0;user-select:none">'
        f'<h3 style="margin:0;font-size:0.9rem;font-weight:700;color:#111827;display:flex;align-items:center;gap:8px">'
        f'<span style="font-size:1rem">{icon}</span>'
        f'<span style="border-left:3px solid {accent};padding-left:8px">{esc(title)}</span>'
        f'</h3>'
        f'<span class="chevron" style="font-size:0.75rem;color:#9ca3af;display:inline-block">▶</span>'
        f'</summary>'
        f'<div style="margin-top:12px">{body_html}</div>'
        f'</details>'
        f'</div>'
    )


def _render_ai_summary(executive_insights: dict, agent_summaries: dict, digest: dict = None) -> str:
    """Render the AI Summary tab — shows only the Executive Digest."""
    if digest:
        digest_html = _render_ai_digest(digest)
        if digest_html:
            return f'<div class="card" style="margin-bottom:12px">{digest_html}</div>'

    return '<p style="color:#6b7280;font-style:italic">No AI analysis available. Run the intelligence pipeline first.</p>'


# Pipeline summary (replaces AI-generated key takeaways)
# ---------------------------------------------------------------------------

def _render_pipeline_summary(
    reconciled_data,
    leakage_findings,
    compliance_findings,
    invoice_draft,
    slack_signals,
    work_units_data,
) -> str:
    """Data-driven combined view: invoice readiness + three insight columns + top actions."""
    # ---- Invoice readiness banner ----
    n_crit_compliance = compliance_findings.get("critical_count", 0) if compliance_findings else 0
    n_crit_leakage    = leakage_findings.get("critical_count", 0)    if leakage_findings    else 0
    has_invoice       = bool(invoice_draft and invoice_draft.get("grand_total", 0) > 0)
    flagged_lines     = sum(
        1 for l in (invoice_draft or {}).get("invoice_lines", []) if l.get("flags")
    ) if invoice_draft else 0

    if n_crit_compliance > 0:
        status, status_color, status_bg = "ACTION REQUIRED", "#dc2626", "#fef2f2"
        status_reason = f"{n_crit_compliance} critical compliance issue(s) must be resolved before sending."
    elif n_crit_leakage > 0:
        status, status_color, status_bg = "NEEDS REVIEW", "#d97706", "#fffbeb"
        status_reason = f"{n_crit_leakage} revenue leakage issue(s) require attention."
    elif flagged_lines > 0:
        status, status_color, status_bg = "NEEDS REVIEW", "#d97706", "#fffbeb"
        status_reason = f"{flagged_lines} invoice line(s) have rate/role flags to confirm."
    elif has_invoice:
        status, status_color, status_bg = "READY", "#16a34a", "#f0fdf4"
        status_reason = "No critical blockers found. Review warnings before sending."
    else:
        status, status_color, status_bg = "INCOMPLETE", "#6b7280", "#f9fafb"
        status_reason = "Intelligence pipeline has not completed — run all agents first."

    readiness_html = (
        f'<div style="display:flex;align-items:center;gap:14px;padding:14px 18px;'
        f'background:{status_bg};border:1px solid {status_color}40;border-radius:8px;margin-bottom:16px">'
        f'<span style="background:{status_color};color:#fff;padding:4px 14px;border-radius:6px;'
        f'font-size:0.82rem;font-weight:700;letter-spacing:.04em;white-space:nowrap">{status}</span>'
        f'<span style="font-size:0.85rem;color:#374151">{esc(status_reason)}</span>'
        f'</div>'
    )

    # ---- Three insight columns ----
    cols = []

    # Column 1: Work & Reconciliation
    if reconciled_data:
        billable_count = reconciled_data.get("billable_count", 0)
        non_billable   = reconciled_data.get("non_billable_count", 0)
        billable_hrs   = reconciled_data.get("total_billable_hours", 0)
        non_bill_hrs   = reconciled_data.get("total_non_billable_hours", 0)
        total_hrs      = billable_hrs + non_bill_hrs
        pct_billable   = (billable_hrs / total_hrs * 100) if total_hrs else 0
        col1_body = (
            f'<div style="font-size:1.5rem;font-weight:800;color:#16a34a">{billable_hrs:,.0f}h</div>'
            f'<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;margin-bottom:10px">Billable Hours</div>'
            f'<div style="font-size:0.82rem;color:#374151;margin-bottom:4px">'
            f'<span style="color:#16a34a;font-weight:600">{billable_count:,}</span> billable'
            f' &nbsp;·&nbsp; '
            f'<span style="color:#6b7280">{non_billable:,}</span> non-billable entries</div>'
            f'<div style="font-size:0.78rem;color:#6b7280">'
            f'{non_bill_hrs:,.0f}h non-billable &nbsp;·&nbsp; {pct_billable:.0f}% utilisation</div>'
        )
        cols.append(("Work Overview", col1_body, "#16a34a"))
    elif work_units_data:
        total_wu = work_units_data.get("total_work_units", 0)
        col1_body = f'<div style="font-size:0.85rem;color:#374151">{total_wu:,} work units normalised.</div>'
        cols.append(("Work Overview", col1_body, "#16a34a"))

    # Column 2: Revenue Risk
    if leakage_findings:
        impact      = leakage_findings.get("total_estimated_impact", 0)
        type_counts = leakage_findings.get("finding_type_counts", {})
        type_rows   = ""
        for ftype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            label      = ftype.replace("_", " ").title()
            type_rows += (
                f'<div style="display:flex;justify-content:space-between;font-size:0.8rem;'
                f'color:#374151;padding:3px 0;border-bottom:1px solid #f3f4f6">'
                f'<span>{esc(label)}</span>'
                f'<span style="font-weight:600;color:#dc2626">{count}</span>'
                f'</div>'
            )
        col2_body = (
            f'<div style="font-size:1.5rem;font-weight:800;color:#dc2626">${impact:,.0f}</div>'
            f'<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;margin-bottom:10px">At Risk</div>'
            f'{type_rows}'
        )
        cols.append(("Revenue Risk", col2_body, "#dc2626"))

    # Column 3: Compliance
    if compliance_findings:
        total_comp  = compliance_findings.get("total_findings", 0)
        crit_comp   = compliance_findings.get("critical_count", 0)
        type_counts = compliance_findings.get("finding_type_counts", {})
        type_rows   = ""
        for ftype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            label      = ftype.replace("_", " ").title()
            type_rows += (
                f'<div style="display:flex;justify-content:space-between;font-size:0.8rem;'
                f'color:#374151;padding:3px 0;border-bottom:1px solid #f3f4f6">'
                f'<span>{esc(label)}</span>'
                f'<span style="font-weight:600;color:#dc2626">{count}</span>'
                f'</div>'
            )
        col3_body = (
            f'<div style="font-size:1.5rem;font-weight:800;color:#dc2626">{crit_comp}</div>'
            f'<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;margin-bottom:10px">Critical Violations</div>'
            f'<div style="font-size:0.78rem;color:#6b7280;margin-bottom:8px">{total_comp:,} total findings</div>'
            f'{type_rows}'
        )
        cols.append(("Compliance", col3_body, "#dc2626"))

    if not cols:
        columns_html = ""
    else:
        col_cards = "".join(
            f'<div style="flex:1;min-width:180px;background:#f9fafb;border-radius:8px;'
            f'padding:14px 16px;border-top:3px solid {col_color}">'
            f'<div style="font-size:0.72rem;text-transform:uppercase;font-weight:700;'
            f'letter-spacing:.05em;color:{col_color};margin-bottom:8px">{esc(col_title)}</div>'
            f'{col_body}'
            f'</div>'
            for col_title, col_body, col_color in cols
        )
        columns_html = (
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">'
            f'{col_cards}'
            f'</div>'
        )

    # ---- Top actions before invoicing ----
    actions: list[tuple[int, str]] = []
    if compliance_findings:
        tc = compliance_findings.get("finding_type_counts", {})
        leave       = tc.get("leave_day_billing", 0)
        unassigned  = tc.get("unassigned_project_billing", 0)
        deactivated = tc.get("deactivated_employee_billing", 0)
        if leave:
            actions.append((leave, f"Reverse {leave} timesheet entries logged on leave days (or revise leave records)."))
        if unassigned:
            actions.append((unassigned, f"Assign {unassigned} unassigned-project entries to valid projects in hr_assignments.csv."))
        if deactivated:
            actions.append((deactivated, f"Remove or approve {deactivated} entries from deactivated employees."))
    if leakage_findings:
        tc       = leakage_findings.get("finding_type_counts", {})
        rate_mm  = tc.get("rate_mismatch", 0)
        unlogged = tc.get("unlogged_work", 0)
        if rate_mm:
            actions.append((rate_mm, f"Correct {rate_mm} rate mismatches in kimai_timesheets.csv to match canonical HR rates."))
        if unlogged:
            actions.append((unlogged, f"Chase {unlogged} missing timesheets from users with Slack/git activity but no logged hours."))
    if flagged_lines:
        actions.append((flagged_lines, f"Resolve {flagged_lines} flagged invoice line(s) (rate fallback or role mismatch) before sending."))

    actions.sort(key=lambda x: -x[0])
    actions = actions[:5]

    if actions:
        action_items = "".join(
            f'<li style="margin-bottom:8px;font-size:0.85rem;color:#374151">{esc(text)}</li>'
            for _, text in actions
        )
        actions_html = (
            f'<div style="margin-top:0">'
            f'<div style="font-size:0.72rem;text-transform:uppercase;font-weight:700;'
            f'letter-spacing:.05em;color:#374151;margin-bottom:8px">Top Actions Before Invoicing</div>'
            f'<ol style="margin:0;padding-left:20px">{action_items}</ol>'
            f'</div>'
        )
    else:
        actions_html = ""

    return readiness_html + columns_html + actions_html


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
details[open] > summary .chevron { transform: rotate(90deg); display: inline-block; }
a { color: #2563eb; }
table td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
table td[style*="color:#374151"] { white-space: normal; overflow: visible; }
table td[style*="font-style:italic"] { white-space: normal; overflow: visible; }
/* ---- Tabs ---- */
.tab-nav {
  display: flex; gap: 4px; flex-wrap: wrap;
  background: #fff; border-radius: 10px; padding: 8px;
  margin-bottom: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.07);
}
.tab-btn {
  border: none; background: transparent; cursor: pointer;
  padding: 7px 14px; border-radius: 7px; font-size: 0.82rem;
  font-weight: 600; color: #6b7280;
  display: flex; align-items: center; gap: 6px; white-space: nowrap;
  transition: background 0.12s, color 0.12s;
}
.tab-btn:hover { background: #f3f4f6; color: #374151; }
.tab-btn.active { background: #2563eb; color: #fff; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
/* ---- Column tooltips ---- */
.col-tip {
  display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; border-radius: 50%;
  background: #9ca3af; color: #fff;
  font-size: 0.6rem; font-weight: 700; line-height: 1;
  cursor: help; margin-left: 4px; vertical-align: middle;
  position: relative; flex-shrink: 0;
}
.col-tip::after {
  content: attr(data-tip);
  display: none; position: absolute;
  top: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  background: #1f2937; color: #f9fafb;
  font-size: 0.72rem; font-weight: 400; line-height: 1.45;
  text-transform: none; letter-spacing: 0;
  padding: 6px 10px; border-radius: 6px;
  white-space: normal; width: 220px;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
  z-index: 100; pointer-events: none;
}
.col-tip:hover::after { display: block; }
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
# Filter bar + JS
# ---------------------------------------------------------------------------

def _render_filter_bar() -> str:
    """Returns filter controls HTML (no outer sticky wrapper — caller wraps)."""
    sel_style = (
        "padding:5px 10px;border:1px solid #d1d5db;border-radius:6px;"
        "font-size:0.82rem;background:#fff;color:#111827;cursor:pointer"
    )
    btn_style = (
        "padding:5px 12px;border:1px solid #d1d5db;border-radius:6px;"
        "font-size:0.82rem;background:#f3f4f6;color:#374151;cursor:pointer"
    )
    return (
        f'<span style="font-weight:700;font-size:0.75rem;text-transform:uppercase;'
        f'letter-spacing:.04em;color:#9ca3af">Filter</span>'
        f'<select id="filter-user" style="{sel_style}">'
        f'<option value="">All Employees</option>'
        f'</select>'
        f'<select id="filter-project" style="{sel_style}">'
        f'<option value="">All Projects</option>'
        f'</select>'
        f'<button id="filter-clear" style="{btn_style}">Clear</button>'
        f'<span id="filter-status" style="font-size:0.78rem;color:#6b7280;margin-left:4px"></span>'
    )


_FILTER_JS = """
<script>
(function () {
  var fd = window._FILTER_DATA || {users: [], projects: []};
  var userSel = document.getElementById('filter-user');
  var projSel = document.getElementById('filter-project');
  var clearBtn = document.getElementById('filter-clear');
  var statusEl = document.getElementById('filter-status');
  if (!userSel || !projSel) return;

  fd.users.forEach(function (u) {
    var o = document.createElement('option');
    o.value = u.toLowerCase(); o.textContent = u;
    userSel.appendChild(o);
  });
  fd.projects.forEach(function (p) {
    var o = document.createElement('option');
    o.value = p.toLowerCase(); o.textContent = p;
    projSel.appendChild(o);
  });

  function applyFilter() {
    var u = userSel.value;
    var p = projSel.value;
    var active = u || p;
    var visible = 0, total = 0;

    // 1. Filter data rows — only apply each axis if the row carries that attribute
    document.querySelectorAll('tr[data-user], tr[data-project]').forEach(function (tr) {
      if (tr.classList.contains('show-more-row')) return;
      total++;
      var uOk = !u || !tr.hasAttribute('data-user')    || tr.dataset.user.indexOf(u)    !== -1;
      var pOk = !p || !tr.hasAttribute('data-project') || tr.dataset.project.indexOf(p) !== -1;
      var show = uOk && pOk;
      tr.style.display = show ? '' : 'none';
      if (show) visible++;
    });

    // 2. When filter active: reveal extra rows for matching; hide show-more buttons.
    //    When cleared: re-hide extra rows and show the buttons again.
    if (active) {
      document.querySelectorAll('.show-more-row').forEach(function (tr) { tr.style.display = 'none'; });
    } else {
      document.querySelectorAll('.extra-row').forEach(function (tr) { tr.style.display = 'none'; });
      document.querySelectorAll('.show-more-row').forEach(function (tr) { tr.style.display = ''; });
    }

    // 3. Hide/show invoice project accordions (details[data-project]) by project filter
    document.querySelectorAll('details[data-project]').forEach(function (det) {
      if (!p) {
        det.style.display = '';
      } else {
        det.style.display = det.dataset.project.indexOf(p) !== -1 ? '' : 'none';
      }
    });

    // 4. Auto open/close inner accordions based on whether they have visible rows
    document.querySelectorAll('details').forEach(function (det) {
      if (det.style.display === 'none') return;
      var rows = det.querySelectorAll('tr[data-user]:not(.show-more-row), tr[data-project]:not(.show-more-row)');
      if (!rows.length) return;
      var hasVisible = Array.from(rows).some(function (r) { return r.style.display !== 'none'; });
      if (active) { det.open = hasVisible; }
    });

    // 5. Update count badges (.dyn-count) in each details summary
    document.querySelectorAll('details').forEach(function (det) {
      var countEl = det.querySelector(':scope > summary .dyn-count');
      if (!countEl) return;
      if (countEl.dataset.orig === undefined) countEl.dataset.orig = countEl.textContent;
      if (!active) {
        countEl.textContent = countEl.dataset.orig;
        return;
      }
      var rows = det.querySelectorAll('tr[data-user]:not(.show-more-row), tr[data-project]:not(.show-more-row)');
      var count = Array.from(rows).filter(function (r) { return r.style.display !== 'none'; }).length;
      countEl.textContent = count;
    });

    if (statusEl) {
      statusEl.textContent = active ? (visible + ' of ' + total + ' rows match') : '';
    }
  }

  userSel.addEventListener('change', applyFilter);
  projSel.addEventListener('change', applyFilter);
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      userSel.value = ''; projSel.value = '';
      applyFilter();
    });
  }
})();
</script>
"""

_TABS_JS = """
<script>
(function() {
  document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
      btn.classList.add('active');
      var panel = document.getElementById('panel-' + btn.dataset.tab);
      if (panel) { panel.classList.add('active'); }
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
    reconciled_data:     dict = None,
    executive_insights:  dict = None,
    contract_model:      dict = None,
) -> str:
    """
    Write output/audit_{version}_{model_short}_YYYY-MM-DD.html and return the file path.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    now         = datetime_cls.now()
    today       = now.strftime("%Y-%m-%d")
    generated_at = now.strftime("%Y-%m-%d %H:%M")
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

    # ---- Collect unique users & projects for filter dropdowns ----
    import json as _json
    _all_users: set = set()
    _all_projects: set = set()
    for _i in issues:
        if _i.get("user"):    _all_users.add(_i["user"])
        if _i.get("project"): _all_projects.add(_i["project"])
    if leakage_findings:
        for _f in leakage_findings.get("findings", []):
            if _f.get("user"):    _all_users.add(_f["user"])
            if _f.get("project"): _all_projects.add(_f["project"])
    if compliance_findings:
        for _f in compliance_findings.get("findings", []):
            if _f.get("user"):    _all_users.add(_f["user"])
            if _f.get("project"): _all_projects.add(_f["project"])
    if invoice_draft:
        for _l in invoice_draft.get("invoice_lines", []):
            if _l.get("user"):    _all_users.add(_l["user"])
            if _l.get("project"): _all_projects.add(_l["project"])
    if proj_budget_hours:
        _all_projects.update(proj_budget_hours.keys())
    if proj_actual_hours:
        _all_projects.update(proj_actual_hours.keys())
    _filter_data_js = (
        f'<script>window._FILTER_DATA = {_json.dumps({"users": sorted(_all_users), "projects": sorted(_all_projects)})};</script>'
    )

    # ---- Load agent summary text files ----
    _SUMMARY_KEYS = [
        "work_units", "slack_signals", "leakage_findings",
        "compliance_findings", "contract_model", "invoice_draft", "reconciled",
    ]
    agent_summaries: dict = {}
    _agent_state_dir = os.path.join(OUT_DIR, "agent_state")
    for _key in _SUMMARY_KEYS:
        _path = os.path.join(_agent_state_dir, f"{_key}_summary.txt")
        if os.path.exists(_path):
            try:
                with open(_path) as _f:
                    agent_summaries[_key] = _f.read()
            except OSError:
                pass

    # ---- Sections ----
    stat_tiles_html = _stat_tiles(
        total_entries, n_crit, n_warn, n_info,
        leakage_findings, compliance_findings, invoice_draft, slack_signals,
    )

    pipeline_summary_html = _render_pipeline_summary(
        reconciled_data, leakage_findings, compliance_findings,
        invoice_draft, slack_signals, work_units_data,
    )

    leakage_html    = _render_leakage(leakage_findings, slack_signals) if leakage_findings else ""
    compliance_html = _render_compliance(compliance_findings) if compliance_findings else ""
    invoice_html    = _render_invoice(invoice_draft)        if invoice_draft        else ""
    budget_html     = _render_budget(
        proj_budget_hours or {}, proj_budget_cost or {},
        proj_actual_hours or {}, proj_actual_cost or {},
        contract_model=contract_model,
    )
    all_issues_html     = _render_all_issues_table(issues, work_units_data, leakage_findings, compliance_findings)
    quality_html        = _render_data_quality(work_units_data)
    _digest             = _synthesize_ai_digest(agent_summaries, OUT_DIR) if agent_summaries else {}
    ai_summary_html     = _render_ai_summary(executive_insights or {}, agent_summaries, digest=_digest)

    # ---- Build tab definitions ----
    tab_defs = []
    if leakage_findings:
        lc = leakage_findings.get("total_findings", 0)
        tab_defs.append(("leakage", "Revenue Leakage", lc, "#dc2626",
                         _tab_section("Revenue Leakage", lc, "#dc2626", leakage_html,
                                      "Hours and rates where revenue may be lost or left uncaptured — "
                                      "rate mismatches, unlogged work, SOW cap overages, and underbilling.")))
    if compliance_findings:
        cc = compliance_findings.get("total_findings", 0)
        tab_defs.append(("compliance", "Compliance", cc, "#dc2626",
                         _tab_section("Compliance Blockers", cc, "#dc2626", compliance_html,
                                      "Policy and contract violations that must be resolved before an invoice "
                                      "can be sent — leave-day billing, unauthorised overtime, deactivated employees.")))
    if invoice_draft:
        ic = invoice_draft.get("line_item_count", 0)
        tab_defs.append(("invoice", "Invoice Draft", ic, "#16a34a",
                         _tab_section("Invoice Draft", ic, "#16a34a", invoice_html,
                                      "Billable work units grouped by project, with rates and flags for "
                                      "role mismatches or missing contract rates. Review before sending to client.")))
    if proj_budget_hours:
        bc = len(proj_budget_hours)
        tab_defs.append(("budget", "Budget", bc, "#7c3aed",
                         _tab_section("Project Budget vs Actuals", bc, "#7c3aed", budget_html,
                                      "Actual hours and cost vs. contracted budget caps per project. "
                                      "OVER means the SOW ceiling has been breached; NEAR means within 10%.")))
    all_issues_count = (
        len(issues)
        + (len(compliance_findings.get("findings", [])) if compliance_findings else 0)
        + (len(leakage_findings.get("findings", []))    if leakage_findings    else 0)
        + (len(work_units_data.get("data_quality_issues", [])) if work_units_data else 0)
    )
    timesheet_tab_body = all_issues_html
    tab_defs.append(("quality", "Timesheet Issues", all_issues_count, "#6b7280",
                     _tab_section("Timesheet Issues", all_issues_count, "#6b7280", timesheet_tab_body,
                                  "All timesheet findings in one place — rule-based check violations and "
                                  "data quality problems, sorted by severity.")))
    tab_defs.append(("ai_summary", "AI Summary", None, "#7c3aed",
                     _tab_section("AI Summary", None, "#7c3aed", ai_summary_html,
                                  "Structured intelligence panel and natural-language summaries from each "
                                  "agent in the audit pipeline — leakage, compliance, invoice, reconciliation.")))

    # ---- Combined sticky nav (tab bar + filter controls) ----
    tab_nav_html = _render_tab_nav(tab_defs) if tab_defs else ""
    tab_panels_html = "".join(
        f'<div id="panel-{tid}" class="tab-panel{" active" if i == 0 else ""}">{content}</div>'
        for i, (tid, _, _, _, content) in enumerate(tab_defs)
    )
    combined_nav_html = (
        f'<div id="sticky-nav" style="position:sticky;top:0;z-index:100;'
        f'background:#f3f4f6;padding:8px 0 4px;margin-bottom:4px">'
        f'{tab_nav_html}'
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
        f'background:#fff;border-radius:10px;padding:8px 16px;margin-bottom:8px;'
        f'box-shadow:0 1px 4px rgba(0,0,0,.06)">'
        f'{_render_filter_bar()}'
        f'</div>'
        f'</div>'
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revenue Intelligence Report — {data_version} {today}</title>
<style>{_CSS}</style>
{_filter_data_js}
</head>
<body>

<!-- HEADER -->
<div class="card" style="margin-bottom:16px">
  <div style="display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:12px">
    <h1 style="margin:0;font-size:1.25rem;font-weight:800">Revenue Intelligence Report</h1>
    <span style="font-size:0.85rem;font-weight:700;color:#7c3aed">{esc(data_version)}</span>
    <span style="font-size:0.78rem;color:#9ca3af">model: {esc(model_short)}</span>
    <span style="font-size:0.78rem;color:#9ca3af">generated {generated_at}</span>
  </div>
  {stat_tiles_html}
</div>

<!-- PIPELINE SUMMARY (collapsible, open by default) -->
<div class="card">
  <details open>
    <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;
                    justify-content:space-between;padding:0;user-select:none">
      <h2 style="margin:0;font-size:1rem;font-weight:700">Invoice Status &amp; Pipeline Summary</h2>
      <span class="chevron" style="font-size:0.75rem;color:#9ca3af;display:inline-block">▶</span>
    </summary>
    <div style="margin-top:14px">{pipeline_summary_html}</div>
  </details>
</div>

<!-- STICKY NAV: tabs + filter -->
{combined_nav_html}

<!-- TAB PANELS -->
{tab_panels_html}

{_SEARCH_JS}
{_FILTER_JS}
{_TABS_JS}
</body>
</html>"""

    out_path = os.path.join(OUT_DIR, f"audit_{data_version}_{model_short}_{today}.html")
    with open(out_path, "w") as f:
        f.write(html_out)
    return out_path
