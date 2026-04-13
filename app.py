"""
Streamlit UI — Revenue Intelligence Auditor

Run:
    python3.11 -m streamlit run app.py
"""
import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent

# ---------------------------------------------------------------------------
# Page config & global CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Revenue Intelligence Auditor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background:#0f1117; }
[data-testid="stSidebar"]          { background:#13151f; border-right:1px solid #1e2130; }
[data-testid="stSidebar"] label    { color:#94a3b8 !important; font-size:0.83rem; }
.stMarkdown h2, .stMarkdown h3     { color:#e2e8f0; }

/* metric tiles */
.tile { background:#1e2130; border:1px solid #2d2f3e; border-radius:10px;
        padding:16px 20px; text-align:center; }
.tile-val { font-size:1.6rem; font-weight:800; color:#e2e8f0; }
.tile-lbl { font-size:0.73rem; color:#64748b; margin-top:4px; }

/* log box */
.log-box { background:#080a10; border:1px solid #1e2130; border-radius:8px;
           padding:12px 14px; font-family:'JetBrains Mono',monospace;
           font-size:0.72rem; color:#94a3b8; height:300px; overflow-y:auto;
           white-space:pre-wrap; word-break:break-all; }

/* hide streamlit chrome */
#MainMenu, footer, header { visibility:hidden; }
div.stButton > button[kind="primary"] {
    background:#3b82f6; border:none; font-weight:700;
    border-radius:8px; width:100%; color:#fff; }
div.stButton > button[kind="primary"]:hover { background:#2563eb; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Pipeline definition  (label, phase, description, file written)
# ---------------------------------------------------------------------------
PIPELINE = [
    ("Normalization Agent",    "Phase 1", "Build WorkUnits",         "work_units.json"),
    ("Contract Agent",         "Phase 1", "Parse SOW → rules",       "contract_model.json"),
    ("Context Mining Agent",   "Phase 1", "Slack → work signals",    "slack_signals.json"),
    ("Reconciliation Agent",   "Phase 2", "Billable / non-billable", "reconciled.json"),
    ("Revenue Leakage Agent",  "Phase 3", "Rate & unlogged billing", "leakage_findings.json"),
    ("Compliance Agent",       "Phase 3", "Policy violations",       "compliance_findings.json"),
    ("Invoice Drafting Agent", "Phase 4", "Draft line items",        "invoice_draft.json"),
    ("Review & Alert Agent",   "Phase 5", "HTML report",             "audit_*.html"),
]

LABELS = [p[0] for p in PIPELINE]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]|[\x00-\x08\x0b-\x1f\x7f]")

def strip_ansi(t: str) -> str:
    return ANSI_RE.sub("", t)

def latest_report(out_dir="output"):
    r = sorted(glob.glob(f"{out_dir}/audit_*.html"))
    return r[-1] if r else None

# ---------------------------------------------------------------------------
# DOT flowchart builder — re-rendered each update with live status colours
# ---------------------------------------------------------------------------
NODE_COLORS = {
    "pending": ("#1e2130", "#4b5563", "#2d2f3e"),   # fill, font, border
    "running": ("#2d1e00", "#fbbf24", "#f59e0b"),
    "done":    ("#0a1f16", "#34d399", "#10b981"),
    "error":   ("#200a0a", "#f87171", "#ef4444"),
}

def build_dot(states: dict) -> str:
    def node(label, display):
        fill, font, border = NODE_COLORS[states[label]["state"]]
        s = states[label]
        timing = ""
        if s["elapsed"] is not None:
            timing = f"\\n{s['elapsed']:.0f}s"
            if s["cost"] is not None:
                timing += f"  ${s['cost']:.4f}"
        return (
            f'  "{label}" ['
            f'label="{display}{timing}" '
            f'fillcolor="{fill}" fontcolor="{font}" color="{border}" '
            f'style="filled,rounded" shape=box fontname="Arial" fontsize=10 '
            f'margin="0.15,0.12" width=1.9'
            f']'
        )

    # Short display names for the graph boxes
    names = {
        "Normalization Agent":    "Normalization\nAgent",
        "Contract Agent":         "Contract\nAgent",
        "Context Mining Agent":   "Context Mining\nAgent",
        "Reconciliation Agent":   "Reconciliation\nAgent",
        "Revenue Leakage Agent":  "Revenue Leakage\nAgent",
        "Compliance Agent":       "Compliance\nAgent",
        "Invoice Drafting Agent": "Invoice Drafting\nAgent",
        "Review & Alert Agent":   "Review & Alert\nAgent",
    }

    lines = [
        'digraph pipeline {',
        '  rankdir=TB',
        '  bgcolor="#0f1117"',
        '  splines=ortho',
        '  nodesep=0.5',
        '  ranksep=0.6',
        '  edge [color="#374151" fontcolor="#6b7280" fontname="Arial" fontsize=8]',
        '',
        '  // Phase 1 — parallel',
        '  subgraph cluster_p1 {',
        '    rank=same',
        '    style=invis',
    ]
    for lbl in ["Normalization Agent", "Contract Agent", "Context Mining Agent"]:
        lines.append(f'    {node(lbl, names[lbl])}')
    lines += [
        '  }',
        '',
        '  // Phase 2',
    ]
    lines.append(f'  {node("Reconciliation Agent", names["Reconciliation Agent"])}')
    lines += [
        '',
        '  // Phase 3 — parallel',
        '  subgraph cluster_p3 {',
        '    rank=same',
        '    style=invis',
    ]
    for lbl in ["Revenue Leakage Agent", "Compliance Agent"]:
        lines.append(f'    {node(lbl, names[lbl])}')
    lines += [
        '  }',
        '',
        '  // Phase 4',
    ]
    lines.append(f'  {node("Invoice Drafting Agent", names["Invoice Drafting Agent"])}')
    lines += [
        '',
        '  // Phase 5',
    ]
    lines.append(f'  {node("Review & Alert Agent", names["Review & Alert Agent"])}')
    lines += [
        '',
        '  // Data flow edges',
        '  "Normalization Agent"   -> "Reconciliation Agent"   [label="work_units"]',
        '  "Contract Agent"        -> "Reconciliation Agent"   [label="contract_model"]',
        '  "Context Mining Agent"  -> "Revenue Leakage Agent"  [label="slack_signals" style=dashed]',
        '  "Reconciliation Agent"  -> "Revenue Leakage Agent"  [label="reconciled"]',
        '  "Reconciliation Agent"  -> "Compliance Agent"       [label="reconciled"]',
        '  "Reconciliation Agent"  -> "Invoice Drafting Agent" [label="reconciled"]',
        '  "Contract Agent"        -> "Invoice Drafting Agent" [label="contract_model" style=dashed]',
        '  "Revenue Leakage Agent" -> "Review & Alert Agent"   [label="leakage"]',
        '  "Compliance Agent"      -> "Review & Alert Agent"   [label="compliance"]',
        '  "Invoice Drafting Agent"-> "Review & Alert Agent"   [label="invoice"]',
        '}',
    ]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def fresh_states():
    return {lbl: {"state": "pending", "elapsed": None, "cost": None} for lbl in LABELS}

if "agent_states" not in st.session_state:
    st.session_state.agent_states = fresh_states()
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []
if "finished" not in st.session_state:
    st.session_state.finished = False

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    data_version = st.selectbox("Data version", ["v5", "v3", "v2", "v1"])
    model = st.selectbox("Agent model", [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    ])
    review_model = st.selectbox("Review model", [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ])
    push_pages = st.checkbox("Push to GitHub Pages", value=False)
    st.markdown("---")
    run_btn = st.button("▶  Run Audit", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown("### Previous Reports")
    for r in sorted(glob.glob("output/audit_*.html"), reverse=True)[:5]:
        name = Path(r).name
        st.download_button(f"⬇ {name}", data=open(r).read(),
                           file_name=name, mime="text/html", key=f"dl_{name}")

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
st.markdown("## 📊 Revenue Intelligence Auditor")
st.caption("8-agent pipeline · timesheet auditing · invoice readiness")

left, right = st.columns([5, 4], gap="large")

with left:
    st.markdown("### Pipeline Flow")
    graph_ph = st.empty()
    graph_ph.graphviz_chart(
        build_dot(st.session_state.agent_states), use_container_width=True
    )

with right:
    st.markdown("### Agent Status")
    status_ph = st.empty()

    def render_status_table(states):
        rows = ""
        for lbl, phase, desc, output_file in PIPELINE:
            s = states[lbl]
            state = s["state"]
            if state == "pending":
                icon, color = "○", "#4b5563"
            elif state == "running":
                icon, color = "⟳", "#f59e0b"
            elif state == "done":
                icon, color = "✓", "#10b981"
            else:
                icon, color = "✗", "#ef4444"
            timing = ""
            if s["elapsed"] is not None:
                timing = f"{s['elapsed']:.0f}s"
                if s["cost"] is not None:
                    timing += f" &middot; &#36;{s['cost']:.4f}"
            rows += f"""
            <tr>
              <td style="padding:7px 10px;color:#6b7280;font-size:0.72rem">{phase}</td>
              <td style="padding:7px 10px">
                <div style="font-weight:600;color:#e2e8f0;font-size:0.82rem">{lbl}</div>
                <div style="color:#4b5563;font-size:0.72rem">{desc}</div>
              </td>
              <td style="padding:7px 10px;font-size:0.8rem;font-weight:700;color:{color};white-space:nowrap">
                {icon} {state}
              </td>
              <td style="padding:7px 10px;color:#64748b;font-size:0.72rem;white-space:nowrap">
                {timing}
              </td>
            </tr>"""
        return f"""
        <table style="width:100%;border-collapse:collapse;background:#0f1117">
          <thead>
            <tr style="border-bottom:1px solid #1e2130">
              <th style="padding:7px 10px;text-align:left;color:#4b5563;font-size:0.7rem;font-weight:600">PHASE</th>
              <th style="padding:7px 10px;text-align:left;color:#4b5563;font-size:0.7rem;font-weight:600">AGENT</th>
              <th style="padding:7px 10px;text-align:left;color:#4b5563;font-size:0.7rem;font-weight:600">STATUS</th>
              <th style="padding:7px 10px;text-align:left;color:#4b5563;font-size:0.7rem;font-weight:600">TIME · COST</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    status_ph.html(render_status_table(st.session_state.agent_states))

st.markdown("---")
st.markdown("### Agent Output")
log_ph = st.empty()
_LOG_STYLE = (
    'background:#080a10;border:1px solid #1e2130;border-radius:8px;'
    'padding:12px 14px;font-family:monospace;font-size:0.72rem;color:#94a3b8;'
    'height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all'
)
log_ph.html(
    f'<div style="{_LOG_STYLE}">'
    f'{chr(10).join(st.session_state.log_lines) or "Waiting for pipeline to start…"}'
    f'</div>'
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if run_btn:
    st.session_state.agent_states = fresh_states()
    st.session_state.log_lines    = []
    st.session_state.finished     = False

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env["DATA_DIR"]          = f"data/{data_version}"
    env["OUT_DIR"]           = "output"
    env["MODEL"]             = model
    env["REVIEW_MODEL"]      = review_model
    env["NO_COLOR"]          = "1"
    env["TERM"]              = "dumb"
    env["PYTHONUNBUFFERED"]  = "1"   # ← ensures line-by-line flush from subprocess

    agent_start_times: dict[str, float] = {}

    # Use the same interpreter that launched Streamlit (should be python3.11)
    python = sys.executable
    with subprocess.Popen(
        [python, str(ROOT / "audit_agent_sdk.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env, cwd=str(ROOT),
    ) as proc:
        for raw in proc.stdout:
            line = strip_ansi(raw).rstrip("\n")
            if not line.strip():
                continue

            # --- detect agent start ---
            m_start = re.match(r"\[AGENT_START\] (.+)", line)
            if m_start:
                lbl = m_start.group(1).strip()
                if lbl in st.session_state.agent_states:
                    st.session_state.agent_states[lbl]["state"] = "running"
                    agent_start_times[lbl] = time.time()

            # --- detect agent done ---
            m_done = re.match(r"\[AGENT_DONE\] (.+?) elapsed=([0-9.]+) cost=([0-9.]+|none)", line)
            if m_done:
                lbl     = m_done.group(1).strip()
                elapsed = float(m_done.group(2))
                cost_s  = m_done.group(3)
                cost    = float(cost_s) if cost_s != "none" else None
                if lbl in st.session_state.agent_states:
                    st.session_state.agent_states[lbl].update(
                        state="done", elapsed=elapsed, cost=cost
                    )

            # --- update log (skip internal marker lines) ---
            if not (line.startswith("[AGENT_START]") or line.startswith("[AGENT_DONE]")):
                st.session_state.log_lines.append(line)
            if len(st.session_state.log_lines) > 200:
                st.session_state.log_lines.pop(0)

            # --- refresh all three UI sections ---
            graph_ph.graphviz_chart(
                build_dot(st.session_state.agent_states), use_container_width=True
            )
            status_ph.html(render_status_table(st.session_state.agent_states))
            log_ph.html(
                f'<div style="{_LOG_STYLE}">'
                f'{chr(10).join(st.session_state.log_lines)}'
                f'</div>'
            )

    proc.wait()
    st.session_state.finished = True

    if push_pages:
        with st.spinner("Pushing to GitHub Pages…"):
            res = subprocess.run(
                ["bash", str(ROOT / "run_local.sh"), data_version],
                capture_output=True, text=True, env=env, cwd=str(ROOT),
            )
        if res.returncode == 0:
            st.success("✓ Pushed to GitHub Pages")
        else:
            st.error(f"Push failed: {res.stderr[-400:]}")

# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------
if st.session_state.finished or latest_report():
    report = latest_report()
    if report:
        st.markdown("---")
        st.markdown("### 📄 Report")

        states = st.session_state.agent_states
        total_cost = sum(s["cost"] for s in states.values() if s.get("cost"))
        total_time = sum(s["elapsed"] for s in states.values() if s.get("elapsed"))
        done_count = sum(1 for s in states.values() if s["state"] == "done")

        c1, c2, c3, c4 = st.columns(4)
        _tile_style = (
            'background:#1e2130;border:1px solid #2d2f3e;border-radius:10px;'
            'padding:16px 20px;text-align:center'
        )
        for col, val, lbl in [
            (c1, f"{done_count}/8",                "Agents completed"),
            (c2, f"{total_time:.0f}s",             "Total time"),
            (c3, f"${total_cost:.4f}",             "Total cost"),
            (c4, Path(report).stem.split("_")[2] if "_" in Path(report).stem else "—", "Data version"),
        ]:
            col.html(
                f'<div style="{_tile_style}">'
                f'<div style="font-size:1.6rem;font-weight:800;color:#e2e8f0">{val}</div>'
                f'<div style="font-size:0.73rem;color:#64748b;margin-top:4px">{lbl}</div>'
                f'</div>'
            )

        st.markdown("<br>", unsafe_allow_html=True)
        with open(report) as f:
            html = f.read()
        st.download_button("⬇ Download Report", data=html,
                           file_name=Path(report).name, mime="text/html")
        st.components.v1.html(html, height=900, scrolling=True)
