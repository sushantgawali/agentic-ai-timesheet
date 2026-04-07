#!/usr/bin/env python3
"""
Generate index.html listing all audit reports found in the given directory.

Usage:
    python3 generate_index.py <reports_dir>
"""
import os
import re
import sys
from datetime import datetime

PATTERN = re.compile(r"^audit_(v\d+)_(\d{4}-\d{2}-\d{2})\.html$")


def generate_index(reports_dir: str) -> str:
    files = sorted(
        [f for f in os.listdir(reports_dir) if PATTERN.match(f)],
        # Sort newest date first, then highest version first
        key=lambda f: (PATTERN.match(f).group(2), PATTERN.match(f).group(1)),
        reverse=True,
    )

    rows = []
    for i, fname in enumerate(files):
        m = PATTERN.match(fname)
        version  = m.group(1)
        date_str = m.group(2)
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display = dt.strftime("%B %d, %Y")
            weekday = dt.strftime("%A")
        except ValueError:
            display = date_str
            weekday = ""

        latest_badge = (
            '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.72rem;font-weight:700;margin-left:8px">Latest</span>'
            if i == 0 else ""
        )
        version_badge = (
            f'<span style="background:#7c3aed;color:#fff;padding:2px 8px;'
            f'border-radius:4px;font-size:0.72rem;font-weight:700">{version}</span>'
        )
        row_bg = "#f0fdf4" if i == 0 else ("" if i % 2 == 0 else "#f9fafb")
        rows.append(
            f'<tr style="background:{row_bg}">'
            f'<td style="padding:10px 16px;white-space:nowrap;font-weight:{"600" if i == 0 else "400"}">'
            f'{display}{latest_badge}</td>'
            f'<td style="padding:10px 16px;color:#6b7280;white-space:nowrap">{weekday}</td>'
            f'<td style="padding:10px 16px;white-space:nowrap">{version_badge}</td>'
            f'<td style="padding:10px 16px">'
            f'<a href="{fname}" style="color:#2563eb;text-decoration:none;font-family:monospace;font-size:0.875rem">'
            f'{fname}</a></td>'
            f'<td style="padding:10px 16px;text-align:right">'
            f'<a href="{fname}" style="background:#2563eb;color:#fff;padding:4px 14px;'
            f'border-radius:6px;font-size:0.8rem;text-decoration:none;white-space:nowrap">Open →</a>'
            f'</td>'
            f'</tr>'
        )

    total = len(files)
    empty_msg = (
        '<tr><td colspan="5" style="padding:24px;text-align:center;color:#6b7280;font-style:italic">'
        "No reports generated yet.</td></tr>"
        if not rows else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Timesheet Audit Reports</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f3f4f6; color: #111827; }}
  .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 24px; margin-bottom: 24px; max-width: 960px; margin-left: auto; margin-right: auto; }}
  h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  .subtitle {{ color: #6b7280; font-size: 0.9rem; margin-bottom: 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  thead tr {{ background: #f9fafb; }}
  th {{ padding: 10px 16px; text-align: left; font-size: 0.75rem; text-transform: uppercase;
        letter-spacing: .05em; color: #6b7280; border-bottom: 2px solid #e5e7eb; }}
  tbody tr:hover {{ filter: brightness(0.97); }}
  td {{ border-bottom: 1px solid #f3f4f6; }}
</style>
</head>
<body>
<div class="card">
  <h1>Timesheet Audit Reports</h1>
  <p class="subtitle">{total} report{"s" if total != 1 else ""} available</p>
</div>
<div class="card" style="padding:0;overflow:hidden">
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Day</th>
        <th>Version</th>
        <th>File</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows) or empty_msg}
    </tbody>
  </table>
</div>
</body>
</html>"""

    out_path = os.path.join(reports_dir, "index.html")
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <reports_dir>", file=sys.stderr)
        sys.exit(1)
    path = generate_index(sys.argv[1])
    print(f"Index written to: {path}")
