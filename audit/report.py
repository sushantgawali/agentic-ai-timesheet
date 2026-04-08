"""
Generate the HTML audit report from issues + hours_issues.

New sections (v2):
  #1 Per-employee summary table   — all employees ranked by issue count
  #2 Per-project summary table    — all projects ranked by issue count
  #3 Interactive filtering        — severity / check / user / project filters on the main table
  #7 Check distribution chart     — CSS horizontal bars, one per check type
  #9 Top-10 leaderboard           — most-flagged employees & projects at a glance
"""
import html
import os
from collections import defaultdict, Counter
from datetime import date as date_cls

OUT_DIR = os.environ.get("OUT_DIR", "output")

SEV_COLOR = {"CRITICAL": "#dc2626", "WARNING": "#d97706", "INFO": "#2563eb"}
SEV_BG    = {"CRITICAL": "#fef2f2", "WARNING": "#fffbeb", "INFO": "#eff6ff"}
SEV_BADGE = {
    "CRITICAL": "background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
    "WARNING":  "background:#d97706;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
    "INFO":     "background:#2563eb;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
}

# Canonical severity for each check (used for chart bar colours)
CHECK_SEVERITY = {
    "CHECK-1": "CRITICAL", "CHECK-2": "CRITICAL", "CHECK-3": "CRITICAL",
    "CHECK-4": "CRITICAL", "CHECK-5": "CRITICAL", "CHECK-10": "CRITICAL",
    "CHECK-6": "WARNING",  "CHECK-7": "WARNING",  "CHECK-8": "WARNING",
    "CHECK-9": "WARNING",  "CHECK-12": "WARNING", "CHECK-14": "WARNING",
    "CHECK-11": "INFO",    "CHECK-13": "INFO",
}


def esc(s: object) -> str:
    return html.escape(str(s))


def badge(sev: str) -> str:
    return f'<span style="{SEV_BADGE[sev]}">{sev}</span>'


# ---------------------------------------------------------------------------
# Derived stats
# ---------------------------------------------------------------------------

def _compute_user_stats(issues: list[dict]) -> dict:
    """Per-user issue counts by severity (excludes CHECK-13 — shown separately)."""
    stats: dict = defaultdict(lambda: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "total": 0})
    for issue in issues:
        if issue["check"] == "CHECK-13":
            continue
        u = issue["user"]
        stats[u][issue["severity"]] += 1
        stats[u]["total"] += 1
    return stats


def _compute_project_stats(issues: list[dict]) -> dict:
    """Per-project issue counts by severity (excludes CHECK-13 and issues with no project)."""
    stats: dict = defaultdict(lambda: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "total": 0})
    for issue in issues:
        if issue["check"] == "CHECK-13":
            continue
        p = issue.get("project", "").strip()
        if not p:
            continue
        stats[p][issue["severity"]] += 1
        stats[p]["total"] += 1
    return stats


# ---------------------------------------------------------------------------
# Feature #7 — Check distribution chart (CSS bars)
# ---------------------------------------------------------------------------

def _check_distribution_chart(issues: list[dict]) -> str:
    from audit.checks import LABELS
    counts = Counter(i["check"] for i in issues)
    if not counts:
        return ""

    items = sorted(counts.items(), key=lambda x: -x[1])
    max_count = max(counts.values())

    rows = []
    for check, count in items:
        sev   = CHECK_SEVERITY.get(check, "INFO")
        color = SEV_COLOR[sev]
        pct   = max(1, round(count / max_count * 100))
        label = LABELS.get(check, check)
        note  = " ·&nbsp;see Detailed Findings" if check == "CHECK-13" else ""
        rows.append(f"""
  <div style="display:flex;align-items:center;gap:10px;margin:5px 0">
    <span style="font-size:0.8rem;font-weight:600;color:#374151;width:240px;text-align:right;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="{esc(check)}">{esc(label)}</span>
    <div style="flex:1;background:#f3f4f6;border-radius:4px;height:18px;min-width:0">
      <div style="width:{pct}%;height:100%;background:{color};border-radius:4px;opacity:0.82;min-width:4px"></div>
    </div>
    <span style="font-size:0.8rem;font-weight:700;color:#111827;width:46px;text-align:right;flex-shrink:0">{count:,}</span>
    <span style="font-size:0.72rem;color:#9ca3af;white-space:nowrap">{esc(check)}{note}</span>
  </div>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 14px;font-size:1rem;font-weight:700">Issues by Check Type</h2>
  <div style="max-width:960px">{''.join(rows)}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Feature #9 — Top-10 leaderboard
# ---------------------------------------------------------------------------

def _leaderboard_rows(stats: dict, limit: int = 10) -> str:
    ranked = sorted(stats.items(), key=lambda x: (-x[1]["total"], -x[1]["CRITICAL"]))[:limit]
    if not ranked:
        return '<p style="color:#6b7280;font-style:italic;font-size:0.85rem">No data.</p>'

    rows = []
    for rank, (name, s) in enumerate(ranked, 1):
        crit_style = "color:#dc2626;font-weight:700" if s["CRITICAL"] else "color:#9ca3af"
        rows.append(f"""
    <tr>
      <td style="padding:6px 8px;color:#9ca3af;font-size:0.8rem;text-align:center">{rank}</td>
      <td style="padding:6px 8px;font-weight:600;font-size:0.85rem">{esc(name)}</td>
      <td style="padding:6px 8px;text-align:right;{crit_style};font-size:0.85rem">{s['CRITICAL']}</td>
      <td style="padding:6px 8px;text-align:right;color:#d97706;font-size:0.85rem">{s['WARNING']}</td>
      <td style="padding:6px 8px;text-align:right;color:#2563eb;font-size:0.85rem">{s['INFO']}</td>
      <td style="padding:6px 8px;text-align:right;font-weight:700;font-size:0.85rem">{s['total']}</td>
    </tr>""")

    th = "padding:6px 8px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;color:#9ca3af;border-bottom:2px solid #f3f4f6"
    return f"""
  <table style="width:100%;border-collapse:collapse">
    <thead><tr>
      <th style="{th}">#</th>
      <th style="{th}">Name</th>
      <th style="{th};text-align:right">Crit</th>
      <th style="{th};text-align:right">Warn</th>
      <th style="{th};text-align:right">Info</th>
      <th style="{th};text-align:right">Total</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>"""


def _top10_leaderboard(user_stats: dict, project_stats: dict) -> str:
    emp_rows  = _leaderboard_rows(user_stats)
    proj_rows = _leaderboard_rows(project_stats)
    return f"""
<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Top 10 Most-Flagged</h2>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <div style="flex:1;min-width:280px">
      <h3 style="margin:0 0 10px;font-size:0.85rem;font-weight:600;color:#374151;text-transform:uppercase;letter-spacing:.04em">Employees</h3>
      {emp_rows}
    </div>
    <div style="flex:1;min-width:280px">
      <h3 style="margin:0 0 10px;font-size:0.85rem;font-weight:600;color:#374151;text-transform:uppercase;letter-spacing:.04em">Projects</h3>
      {proj_rows}
    </div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Feature #1 — Per-employee summary table
# ---------------------------------------------------------------------------

def _employee_summary_table(user_stats: dict) -> str:
    ranked = sorted(user_stats.items(), key=lambda x: (-x[1]["total"], -x[1]["CRITICAL"]))
    if not ranked:
        return ""

    th = "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb"
    rows = []
    for rank, (user, s) in enumerate(ranked, 1):
        bg         = "#fef2f2" if s["CRITICAL"] > 0 else "#fff"
        crit_style = "color:#dc2626;font-weight:700" if s["CRITICAL"] else "color:#9ca3af"
        rows.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:6px 12px;color:#9ca3af;font-size:0.8rem;text-align:center">{rank}</td>'
            f'<td style="padding:6px 12px;font-weight:600">{esc(user)}</td>'
            f'<td style="padding:6px 12px;text-align:right;{crit_style}">{s["CRITICAL"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;color:#d97706">{s["WARNING"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;color:#2563eb">{s["INFO"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;font-weight:700">{s["total"]}</td>'
            f'</tr>'
        )

    return f"""
<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Per-Employee Summary
    <span style="font-weight:400;color:#6b7280;font-size:0.8rem;margin-left:8px">{len(ranked)} employees with issues &nbsp;·&nbsp; excludes Hours Accuracy check</span>
  </h2>
  <div style="overflow-x:auto;overflow-y:auto;max-height:400px;border:1px solid #e5e7eb;border-radius:6px">
  <table>
    <thead style="position:sticky;top:0;z-index:1"><tr>
      <th style="{th}">#</th>
      <th style="{th}">Employee</th>
      <th style="{th};text-align:right">Critical</th>
      <th style="{th};text-align:right">Warning</th>
      <th style="{th};text-align:right">Info</th>
      <th style="{th};text-align:right">Total</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Feature #2 — Per-project summary table
# ---------------------------------------------------------------------------

def _project_summary_table(project_stats: dict) -> str:
    ranked = sorted(project_stats.items(), key=lambda x: (-x[1]["total"], -x[1]["CRITICAL"]))
    if not ranked:
        return ""

    th = "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb"
    rows = []
    for rank, (proj, s) in enumerate(ranked, 1):
        bg         = "#fef2f2" if s["CRITICAL"] > 0 else "#fff"
        crit_style = "color:#dc2626;font-weight:700" if s["CRITICAL"] else "color:#9ca3af"
        rows.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:6px 12px;color:#9ca3af;font-size:0.8rem;text-align:center">{rank}</td>'
            f'<td style="padding:6px 12px;font-weight:600">{esc(proj)}</td>'
            f'<td style="padding:6px 12px;text-align:right;{crit_style}">{s["CRITICAL"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;color:#d97706">{s["WARNING"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;color:#2563eb">{s["INFO"]}</td>'
            f'<td style="padding:6px 12px;text-align:right;font-weight:700">{s["total"]}</td>'
            f'</tr>'
        )

    return f"""
<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Per-Project Summary
    <span style="font-weight:400;color:#6b7280;font-size:0.8rem;margin-left:8px">{len(ranked)} projects with issues &nbsp;·&nbsp; excludes Hours Accuracy check</span>
  </h2>
  <div style="overflow-x:auto;overflow-y:auto;max-height:400px;border:1px solid #e5e7eb;border-radius:6px">
  <table>
    <thead style="position:sticky;top:0;z-index:1"><tr>
      <th style="{th}">#</th>
      <th style="{th}">Project</th>
      <th style="{th};text-align:right">Critical</th>
      <th style="{th};text-align:right">Warning</th>
      <th style="{th};text-align:right">Info</th>
      <th style="{th};text-align:right">Total</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Project budget vs actuals table
# ---------------------------------------------------------------------------

def _project_budget_table(
    proj_budget_hours: dict,
    proj_budget_cost:  dict,
    proj_actual_hours: dict,
    proj_actual_cost:  dict,
) -> str:
    """
    Full project-by-project comparison: budget hours & cost vs actuals from timesheets.
    All projects in pm_projects.csv are shown regardless of whether they have issues.
    """
    if not proj_budget_hours:
        return ""

    # Build rows sorted by % budget consumed descending
    rows_data = []
    all_projects = set(proj_budget_hours) | set(proj_actual_hours)
    for proj in sorted(all_projects):
        bh = proj_budget_hours.get(proj, 0.0)
        ah = proj_actual_hours.get(proj, 0.0)
        bc = proj_budget_cost.get(proj, 0.0)
        ac = proj_actual_cost.get(proj, 0.0)
        pct_h = (ah / bh * 100) if bh > 0 else None
        pct_c = (ac / bc * 100) if bc > 0 else None
        rows_data.append((proj, bh, ah, bc, ac, pct_h, pct_c))

    rows_data.sort(key=lambda x: -(x[5] or 0))

    th = "padding:8px 12px;font-size:0.7rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;text-align:right;white-space:nowrap"
    th_l = th.replace("text-align:right;", "")

    def _bar(pct) -> str:
        if pct is None:
            return '<span style="color:#9ca3af;font-size:0.75rem">—</span>'
        capped = min(pct, 100)
        color  = "#dc2626" if pct > 100 else "#d97706" if pct > 90 else "#16a34a"
        return (
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="flex:1;background:#f3f4f6;border-radius:3px;height:10px;min-width:60px">'
            f'<div style="width:{capped:.0f}%;height:100%;background:{color};border-radius:3px;min-width:3px"></div>'
            f'</div>'
            f'<span style="font-size:0.78rem;font-weight:700;color:{color};width:42px;text-align:right">{pct:.0f}%</span>'
            f'</div>'
        )

    def _delta(actual: float, budget: float) -> str:
        if budget == 0:
            return '<span style="color:#9ca3af">—</span>'
        diff  = actual - budget
        color = "#dc2626" if diff > 0 else "#16a34a" if diff < 0 else "#6b7280"
        sign  = "+" if diff > 0 else ""
        return f'<span style="color:{color};font-weight:600">{sign}{diff:,.1f}</span>'

    def _cost_delta(actual: float, budget: float) -> str:
        if budget == 0:
            return '<span style="color:#9ca3af">—</span>'
        diff  = actual - budget
        color = "#dc2626" if diff > 0 else "#16a34a" if diff < 0 else "#6b7280"
        sign  = "+" if diff > 0 else ""
        return f'<span style="color:{color};font-weight:600">{sign}${diff:,.0f}</span>'

    td = "padding:7px 12px;border-bottom:1px solid #f3f4f6;font-size:0.83rem"
    rows_html = []
    for proj, bh, ah, bc, ac, pct_h, pct_c in rows_data:
        bg = "#fef2f2" if (pct_h or 0) > 100 else "#fffbeb" if (pct_h or 0) > 90 else "#fff"
        rows_html.append(
            f'<tr style="background:{bg}">'
            f'<td style="{td};font-weight:600;white-space:nowrap">{esc(proj)}</td>'
            f'<td style="{td};text-align:right">{bh:,.0f}</td>'
            f'<td style="{td};text-align:right">{ah:,.1f}</td>'
            f'<td style="{td};text-align:right">{_delta(ah, bh)}</td>'
            f'<td style="{td};min-width:140px">{_bar(pct_h)}</td>'
            f'<td style="{td};text-align:right">${bc:,.0f}</td>'
            f'<td style="{td};text-align:right">${ac:,.0f}</td>'
            f'<td style="{td};text-align:right">{_cost_delta(ac, bc)}</td>'
            f'</tr>'
        )

    over  = sum(1 for *_, pct_h, _ in rows_data if (pct_h or 0) > 100)
    near  = sum(1 for *_, pct_h, _ in rows_data if 90 < (pct_h or 0) <= 100)

    legend = ""
    if over:
        legend += f'<span style="background:#fef2f2;color:#dc2626;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;margin-right:6px">{over} over budget</span>'
    if near:
        legend += f'<span style="background:#fffbeb;color:#d97706;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;margin-right:6px">{near} near limit</span>'

    return f"""
<div class="card">
  <h2 style="margin:0 0 6px;font-size:1rem;font-weight:700">Project Budget vs Actuals
    <span style="font-weight:400;color:#6b7280;font-size:0.8rem;margin-left:8px">hours and cost from timesheets vs pm_projects.csv budgets</span>
  </h2>
  <div style="margin-bottom:14px">{legend}</div>
  <div style="overflow-x:auto;overflow-y:auto;max-height:480px;border:1px solid #e5e7eb;border-radius:6px">
  <table>
    <thead style="position:sticky;top:0;z-index:1"><tr>
      <th style="{th_l}">Project</th>
      <th style="{th}">Budget h</th>
      <th style="{th}">Actual h</th>
      <th style="{th}">Hours Δ</th>
      <th style="{th};text-align:left">% Used</th>
      <th style="{th}">Budget $</th>
      <th style="{th}">Actual $</th>
      <th style="{th}">Cost Δ</th>
    </tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Feature #3 — Filter controls + JS
# ---------------------------------------------------------------------------

def _filter_controls(issues: list[dict]) -> str:
    from audit.checks import LABELS
    checks   = sorted({i["check"] for i in issues if i["check"] != "CHECK-13"})
    chk_opts = "".join(
        f'<option value="{c}">{esc(LABELS.get(c, c))}</option>'
        for c in checks
    )
    sel = "padding:6px 10px;border:1px solid #e5e7eb;border-radius:6px;font-size:0.82rem;background:#fff;color:#374151"
    inp = "padding:6px 10px;border:1px solid #e5e7eb;border-radius:6px;font-size:0.82rem;background:#fff;color:#374151;width:130px"
    return f"""
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
    <select id="f-sev" style="{sel}">
      <option value="">All severities</option>
      <option value="CRITICAL">CRITICAL</option>
      <option value="WARNING">WARNING</option>
      <option value="INFO">INFO</option>
    </select>
    <select id="f-chk" style="{sel}">
      <option value="">All checks</option>
      {chk_opts}
    </select>
    <input id="f-usr"  type="text" placeholder="Filter by user…"    style="{inp}">
    <input id="f-proj" type="text" placeholder="Filter by project…" style="{inp}">
    <button id="f-clear" style="padding:6px 12px;border:1px solid #e5e7eb;border-radius:6px;font-size:0.82rem;background:#f9fafb;cursor:pointer">Clear</button>
    <span style="margin-left:4px;font-size:0.82rem;color:#6b7280">Showing <b id="visible-count">—</b> issues</span>
  </div>"""


_FILTER_JS = """
<script>
(function(){
  var rows = document.querySelectorAll('#issues-tbody tr');
  function applyFilters(){
    var sev  = document.getElementById('f-sev').value;
    var chk  = document.getElementById('f-chk').value;
    var usr  = document.getElementById('f-usr').value.toLowerCase().trim();
    var proj = document.getElementById('f-proj').value.toLowerCase().trim();
    var vis  = 0;
    rows.forEach(function(tr){
      var show = true;
      if(sev  && tr.dataset.severity !== sev)              show = false;
      if(chk  && tr.dataset.check    !== chk)              show = false;
      if(usr  && tr.dataset.user.indexOf(usr)    === -1)   show = false;
      if(proj && tr.dataset.project.indexOf(proj)=== -1)   show = false;
      tr.style.display = show ? '' : 'none';
      if(show) vis++;
    });
    document.getElementById('visible-count').textContent = vis.toLocaleString();
  }
  ['f-sev','f-chk'].forEach(function(id){
    document.getElementById(id).addEventListener('change', applyFilters);
  });
  ['f-usr','f-proj'].forEach(function(id){
    document.getElementById(id).addEventListener('input', applyFilters);
  });
  document.getElementById('f-clear').addEventListener('click', function(){
    ['f-sev','f-chk'].forEach(function(id){ document.getElementById(id).value=''; });
    ['f-usr','f-proj'].forEach(function(id){ document.getElementById(id).value=''; });
    applyFilters();
  });
  applyFilters();
})();
</script>"""


# ---------------------------------------------------------------------------
# Existing helpers (hours table, detail card, key takeaways)
# ---------------------------------------------------------------------------

def _hours_table(hours_issues: list[dict]) -> str:
    if not hours_issues:
        return '<p style="margin:4px 0;color:#6b7280;font-style:italic">No issues found.</p>'

    th = "padding:8px 10px;text-align:left;font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;border-bottom:2px solid #e5e7eb;white-space:nowrap"
    td = "padding:6px 10px;font-size:0.82rem;border-bottom:1px solid #f3f4f6"

    rows = []
    for r in sorted(hours_issues, key=lambda x: (x["user"], x["date"])):
        diff_abs   = abs(r["diff"])
        diff_color = "#dc2626" if diff_abs >= 0.4 else "#d97706" if diff_abs >= 0.25 else "#6b7280"
        rows.append(
            f'<tr>'
            f'<td style="{td};color:#9ca3af">#{r["row"]}</td>'
            f'<td style="{td};font-weight:600">{esc(r["user"])}</td>'
            f'<td style="{td};white-space:nowrap">{esc(r["date"])}</td>'
            f'<td style="{td}">{esc(r["project"])}</td>'
            f'<td style="{td}">{esc(r["activity"])}</td>'
            f'<td style="{td};text-align:right">{r["declared"]}</td>'
            f'<td style="{td};text-align:right">{r["calc"]}</td>'
            f'<td style="{td};text-align:right;font-weight:700;color:{diff_color}">{r["diff"]:+.2f}</td>'
            f'</tr>'
        )
    return (
        f'<div style="overflow-x:auto">'
        f'<table style="width:100%;border-collapse:collapse;font-size:0.875rem">'
        f'<thead><tr>'
        f'<th style="{th}">Row</th>'
        f'<th style="{th}">User</th>'
        f'<th style="{th}">Date</th>'
        f'<th style="{th}">Project</th>'
        f'<th style="{th}">Activity</th>'
        f'<th style="{th};text-align:right">Declared (h)</th>'
        f'<th style="{th};text-align:right">Calculated (h)</th>'
        f'<th style="{th};text-align:right">Diff (h)</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table></div>'
    )


def _detail_card(check_id: str, label: str, findings: list[dict], hours_issues: list[dict]) -> str:
    sev_color = SEV_COLOR["INFO"]
    count = len(findings)

    if check_id == "CHECK-13":
        body = _hours_table(hours_issues)
    elif findings:
        lis = "".join(
            f'<li style="margin:2px 0;font-family:monospace;font-size:0.85rem">{esc(f["detail"])}</li>'
            for f in findings
        )
        body = f'<ul style="margin:6px 0 0 0;padding-left:1.2em">{lis}</ul>'
    else:
        body = '<p style="margin:4px 0;color:#6b7280;font-style:italic">No issues found.</p>'

    return (
        f'<div style="margin-bottom:16px;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden">'
        f'<div style="padding:8px 14px;background:#f9fafb;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;gap:10px">'
        f'<span style="font-weight:700;color:{sev_color}">{esc(label)}</span>'
        f'<span style="margin-left:auto;font-size:0.8rem;color:#6b7280">{count} finding{"s" if count != 1 else ""}</span>'
        f'</div>'
        f'<div style="padding:8px 14px">{body}</div>'
        f'</div>'
    )


def _key_takeaways_html(takeaways: list[str]) -> str:
    if not takeaways:
        return ""
    items = "".join(
        f'<li style="margin:8px 0;padding-left:4px">{esc(t)}</li>'
        for t in takeaways
    )
    return f"""
<div class="card">
  <h2 style="margin:0 0 14px;font-size:1rem;font-weight:700;display:flex;align-items:center;gap:8px">
    <span style="background:#7c3aed;color:#fff;border-radius:6px;padding:3px 10px;font-size:0.78rem;font-weight:700;letter-spacing:.03em">AI</span>
    Key Takeaways
  </h2>
  <ul style="margin:0;padding-left:1.4em;color:#374151;line-height:1.7;font-size:0.92rem">
    {items}
  </ul>
</div>"""


def _model_short(model: str) -> str:
    for key in ("haiku", "sonnet", "opus"):
        if key in model.lower():
            return key
    return model.split("/")[-1]


# ---------------------------------------------------------------------------
# Main generate function
# ---------------------------------------------------------------------------

def generate(
    issues: list[dict],
    hours_issues: list[dict],
    total_entries: int,
    key_takeaways: list = None,
    data_version: str = "v3",
    model: str = "claude-haiku-4-5-20251001",
    proj_budget_hours: dict = None,
    proj_budget_cost:  dict = None,
    proj_actual_hours: dict = None,
    proj_actual_cost:  dict = None,
) -> str:
    """
    Write output/audit_{version}_{model_short}_YYYY-MM-DD.html and return the file path.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    today      = date_cls.today().isoformat()
    model_short = _model_short(model)

    n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
    n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
    n_info = sum(1 for i in issues if i["severity"] == "INFO")

    # --- Derived stats for new sections ---
    user_stats    = _compute_user_stats(issues)
    project_stats = _compute_project_stats(issues)

    # --- Feature #7: check distribution chart ---
    chart_html = _check_distribution_chart(issues)

    # --- Feature #9: top-10 leaderboard ---
    leaderboard_html = _top10_leaderboard(user_stats, project_stats)

    # --- Feature #1: per-employee table ---
    employee_table_html = _employee_summary_table(user_stats)

    # --- Feature #2: per-project table ---
    project_table_html = _project_summary_table(project_stats)

    # --- Project budget vs actuals ---
    budget_table_html = _project_budget_table(
        proj_budget_hours or {},
        proj_budget_cost  or {},
        proj_actual_hours or {},
        proj_actual_cost  or {},
    )

    # --- Feature #3: all-issues table with data-* attributes + filter controls ---
    # Exclude CHECK-13 (shown in Detailed Findings with its own table)
    filterable_issues = [i for i in issues if i["check"] != "CHECK-13"]
    rows_html = []
    for issue in filterable_issues:
        bg      = SEV_BG[issue["severity"]]
        proj_lc = issue.get("project", "").lower()
        rows_html.append(
            f'<tr style="background:{bg}" '
            f'data-severity="{esc(issue["severity"])}" '
            f'data-check="{esc(issue["check"])}" '
            f'data-user="{esc(issue["user"].lower())}" '
            f'data-project="{esc(proj_lc)}">'
            f'<td style="padding:6px 12px;white-space:nowrap">{badge(issue["severity"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap;font-weight:600">{esc(issue["label"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap">{esc(issue["user"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap">{esc(issue["date"])}</td>'
            f'<td style="padding:6px 12px">{esc(issue["brief"])}</td>'
            f'</tr>'
        )

    filter_controls = _filter_controls(filterable_issues)

    # --- Detailed findings section (CHECK-11 + CHECK-13) ---
    detail_checks = ["CHECK-11", "CHECK-13"]
    from audit.checks import LABELS
    issues_by_check: dict[str, list] = {c: [i for i in issues if i["check"] == c] for c in detail_checks}
    detail_items = "".join(
        _detail_card(c, LABELS[c], issues_by_check[c], hours_issues)
        for c in detail_checks
    )

    takeaways_html = _key_takeaways_html(key_takeaways or [])

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Timesheet Audit {data_version} — {today}</title>
<meta name="audit-version" content="{data_version}">
<meta name="audit-model" content="{model_short}">
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f3f4f6; color: #111827; }}
  .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 24px; margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  .subtitle {{ color: #6b7280; font-size: 0.9rem; margin-bottom: 20px; }}
  .stat-grid {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ flex: 1; min-width: 140px; border-radius: 8px; padding: 16px 20px; }}
  .stat .num {{ font-size: 2rem; font-weight: 800; }}
  .stat .lbl {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  thead tr {{ background: #f9fafb; }}
  th {{ padding: 10px 12px; text-align: left; font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em; color: #6b7280; border-bottom: 2px solid #e5e7eb; }}
  tbody tr:hover {{ filter: brightness(0.97); }}
  td {{ border-bottom: 1px solid #f3f4f6; }}
  h2 {{ font-size: 1rem; }}
</style>
</head>
<body>

<div class="card">
  <h1>Timesheet Audit Report</h1>
  <div style="display:flex;align-items:baseline;gap:16px;margin:6px 0 4px;flex-wrap:wrap">
    <span style="font-size:1.6rem;font-weight:800;color:#7c3aed">{data_version}</span>
    <span style="font-size:1.6rem;font-weight:800;color:#1e293b">{model_short}</span>
  </div>
  <p class="subtitle">generated {today}</p>
  <div class="stat-grid">
    <div class="stat" style="background:#f0fdf4">
      <div class="num" style="color:#16a34a">{total_entries:,}</div>
      <div class="lbl" style="color:#15803d">Entries Audited</div>
    </div>
    <div class="stat" style="background:#fef2f2">
      <div class="num" style="color:#dc2626">{n_crit:,}</div>
      <div class="lbl" style="color:#b91c1c">Critical Issues</div>
    </div>
    <div class="stat" style="background:#fffbeb">
      <div class="num" style="color:#d97706">{n_warn:,}</div>
      <div class="lbl" style="color:#b45309">Warnings</div>
    </div>
    <div class="stat" style="background:#eff6ff">
      <div class="num" style="color:#2563eb">{n_info:,}</div>
      <div class="lbl" style="color:#1d4ed8">Info</div>
    </div>
  </div>
</div>

{leaderboard_html}

{takeaways_html}

{chart_html}

{employee_table_html}

{project_table_html}

{budget_table_html}

<div class="card">
  <h2 style="margin:0 0 4px;font-size:1rem;font-weight:700">All Issues</h2>
  <p style="margin:0 0 14px;font-size:0.8rem;color:#6b7280">CHECK-13 (hours accuracy) is excluded here — see Detailed Findings below.</p>
  {filter_controls}
  <div style="overflow-x:auto;overflow-y:auto;max-height:560px;border:1px solid #e5e7eb;border-radius:6px">
  <table id="issues-table">
    <thead style="position:sticky;top:0;z-index:1"><tr>
      <th>Severity</th><th>Check</th><th>User</th><th>Date</th><th>Issue</th>
    </tr></thead>
    <tbody id="issues-tbody">{"".join(rows_html)}</tbody>
  </table>
  </div>
</div>

<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Detailed Findings</h2>
  {detail_items}
</div>

{_FILTER_JS}
</body>
</html>"""

    out_path = os.path.join(OUT_DIR, f"audit_{data_version}_{model_short}_{today}.html")
    with open(out_path, "w") as f:
        f.write(html_out)
    return out_path
