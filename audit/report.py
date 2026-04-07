"""
Generate the HTML audit report from issues + hours_issues.
"""
import html
import os
from datetime import date as date_cls

OUT_DIR = os.environ.get("OUT_DIR", "output")

SEV_COLOR = {"CRITICAL": "#dc2626", "WARNING": "#d97706", "INFO": "#2563eb"}
SEV_BG    = {"CRITICAL": "#fef2f2", "WARNING": "#fffbeb", "INFO": "#eff6ff"}
SEV_BADGE = {
    "CRITICAL": "background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
    "WARNING":  "background:#d97706;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
    "INFO":     "background:#2563eb;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700",
}


def esc(s: object) -> str:
    return html.escape(str(s))


def badge(sev: str) -> str:
    return f'<span style="{SEV_BADGE[sev]}">{sev}</span>'


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


def generate(
    issues: list[dict],
    hours_issues: list[dict],
    total_entries: int,
    key_takeaways: list = None,
    data_version: str = "v3",
) -> str:
    """
    Write output/audit_{version}_YYYY-MM-DD.html and return the file path.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    today = date_cls.today().isoformat()

    n_crit = sum(1 for i in issues if i["severity"] == "CRITICAL")
    n_warn = sum(1 for i in issues if i["severity"] == "WARNING")
    n_info = sum(1 for i in issues if i["severity"] == "INFO")

    # All-issues table rows (exclude CHECK-13)
    rows_html = []
    for issue in issues:
        if issue["check"] == "CHECK-13":
            continue
        bg = SEV_BG[issue["severity"]]
        rows_html.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:6px 12px;white-space:nowrap">{badge(issue["severity"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap;font-weight:600">{esc(issue["label"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap">{esc(issue["user"])}</td>'
            f'<td style="padding:6px 12px;white-space:nowrap">{esc(issue["date"])}</td>'
            f'<td style="padding:6px 12px">{esc(issue["brief"])}</td>'
            f'</tr>'
        )

    # Detailed findings section — weekend + hours accuracy only
    detail_checks = ["CHECK-11", "CHECK-13"]
    from audit.checks import LABELS
    issues_by_check: dict[str, list] = {}
    for c in detail_checks:
        issues_by_check[c] = [i for i in issues if i["check"] == c]

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
  <p class="subtitle">
    <span style="background:#7c3aed;color:#fff;border-radius:4px;padding:1px 8px;font-size:0.78rem;font-weight:700;margin-right:6px">{data_version}</span>
    kimai_timesheets.csv &mdash; generated {today}
  </p>
  <div class="stat-grid">
    <div class="stat" style="background:#f0fdf4">
      <div class="num" style="color:#16a34a">{total_entries}</div>
      <div class="lbl" style="color:#15803d">Entries Audited</div>
    </div>
    <div class="stat" style="background:#fef2f2">
      <div class="num" style="color:#dc2626">{n_crit}</div>
      <div class="lbl" style="color:#b91c1c">Critical Issues</div>
    </div>
    <div class="stat" style="background:#fffbeb">
      <div class="num" style="color:#d97706">{n_warn}</div>
      <div class="lbl" style="color:#b45309">Warnings</div>
    </div>
    <div class="stat" style="background:#eff6ff">
      <div class="num" style="color:#2563eb">{n_info}</div>
      <div class="lbl" style="color:#1d4ed8">Info</div>
    </div>
  </div>
</div>

{takeaways_html}

<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">All Issues</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Severity</th><th>Check</th><th>User</th><th>Date</th><th>Issue</th>
    </tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
  </div>
</div>

<div class="card">
  <h2 style="margin:0 0 16px;font-size:1rem;font-weight:700">Detailed Findings</h2>
  {detail_items}
</div>
</body>
</html>"""

    out_path = os.path.join(OUT_DIR, f"audit_{data_version}_{today}.html")
    with open(out_path, "w") as f:
        f.write(html_out)
    return out_path
