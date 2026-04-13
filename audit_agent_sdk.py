#!/usr/bin/env python3
"""
Multi-agent Revenue Intelligence Orchestrator — Agent SDK entry point.

Runs eight focused sub-agents in a directed pipeline that prioritises:
  • Revenue leakage detection
  • Contract compliance checks
  • Missing / inconsistent data flags
  • Slack-based work detection

Pipeline (numbers indicate parallelism):
  1a. Normalization Agent   ─┐
  1b. Contract Agent        ─┼─ (parallel)
  1c. Context Mining Agent  ─┘
  2.  Reconciliation Agent
  3a. Revenue Leakage Agent ─┐ (parallel)
  3b. Compliance Agent      ─┘
  4.  Invoice Drafting Agent
  5.  Review & Alert Agent

Each sub-agent calls focused MCP tools, reasons over the results, and
writes structured output to the shared agent_state/ directory so the next
phase can consume it.

Requires:
    pip install claude-agent-sdk mcp anyio
    npm install -g @anthropic-ai/claude-code

Required env var: ANTHROPIC_API_KEY
Optional env vars:
    DATA_DIR  (default: data)
    OUT_DIR   (default: output)
    MODEL     (default: claude-haiku-4-5-20251001)
"""
import os
import sys
import time
from pathlib import Path

import anyio

from claude_agent_sdk import (
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    query,
)

from audit import prompts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL        = os.environ.get("MODEL",        "claude-haiku-4-5-20251001")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "claude-sonnet-4-6")
DATA_DIR     = os.environ.get("DATA_DIR", "data")
OUT_DIR      = os.environ.get("OUT_DIR",  "output")
SERVER_SCRIPT = str(Path(__file__).parent / "audit" / "mcp_server.py")

# Set RESUME=1 to skip any agent whose state file already exists in OUT_DIR/agent_state/.
# The agent's previous text summary is restored from a companion .txt cache file.
RESUME = os.environ.get("RESUME", "0") == "1"

# Seconds to wait between launching parallel agents in the same phase.
# Helps avoid simultaneous request spikes when hitting rate limits.
# Set to 0 to disable.
STAGGER_DELAY = float(os.environ.get("STAGGER_DELAY", "3"))

# Maps agent label → agent_state/<key>.json produced by that agent.
# Used by the resume logic to decide whether to skip a run.
_STATE_FILE_MAP: dict[str, str] = {
    "Normalization Agent":    "work_units",
    "Contract Agent":         "contract_model",
    "Context Mining Agent":   "slack_signals",
    "Reconciliation Agent":   "reconciled",
    "Revenue Leakage Agent":  "leakage_findings",
    "Compliance Agent":       "compliance_findings",
    "Invoice Drafting Agent": "invoice_draft",
    "Digest Agent":           "ai_digest",
}


def _python_exe() -> str:
    """Return python3.11+ if available (mcp requires >=3.10), else python3."""
    import shutil
    for candidate in ("python3.11", "python3.12", "python3.10", "python3"):
        exe = shutil.which(candidate)
        if exe:
            return exe
    return "python3"


def _mcp_options(max_turns: int = 6, model: str = MODEL) -> ClaudeAgentOptions:
    """Return ClaudeAgentOptions wired to the shared MCP server."""
    return ClaudeAgentOptions(
        model=model,
        mcp_servers={
            "audit": {
                "type":    "stdio",
                "command": _python_exe(),
                "args":    [SERVER_SCRIPT],
                "env": {
                    "DATA_DIR":   DATA_DIR,
                    "OUT_DIR":    OUT_DIR,
                    "PYTHONPATH": str(Path(__file__).parent),
                },
            }
        },
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )


async def _run_agent(
    label: str, prompt: str, max_turns: int = 6, model: str = MODEL,
) -> str:
    """
    Run a single sub-agent, stream its output, and return the concatenated text.

    Resume behaviour (RESUME=1):
      If this agent has a known state file key in _STATE_FILE_MAP and the
      corresponding JSON file already exists, the agent is skipped and the
      cached summary (stored as <key>_summary.txt) is returned instead.

    Retry behaviour:
      On transient errors (overload, connection issues), retries up to 2 times
      with exponential backoff (10s, 30s).
    """
    state_key = _STATE_FILE_MAP.get(label)
    if RESUME and state_key:
        state_path   = Path(OUT_DIR) / "agent_state" / f"{state_key}.json"
        summary_path = Path(OUT_DIR) / "agent_state" / f"{state_key}_summary.txt"
        if state_path.exists():
            cached = summary_path.read_text() if summary_path.exists() else (
                f"[skipped — state already exists: {state_path}]"
            )
            print(f"[AGENT_SKIP] {label}", flush=True)
            return cached

    print(f"[AGENT_START] {label}", flush=True)

    _MAX_RETRIES   = 2
    _RETRY_DELAYS  = [10, 30]  # seconds between attempts 1→2, 2→3
    _TRANSIENT_KEYWORDS = ("overloaded", "overload", "rate limit", "429",
                           "connection", "timeout", "temporarily")

    def _is_transient(exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(kw in msg for kw in _TRANSIENT_KEYWORDS)

    started_at = time.time()
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            delay = _RETRY_DELAYS[attempt - 1]
            print(f"[AGENT_RETRY] {label} attempt={attempt} delay={delay}", flush=True)
            await anyio.sleep(delay)

        text_parts: list[str] = []
        options = _mcp_options(max_turns=max_turns, model=model)

        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    cost_usd = message.total_cost_usd
                    elapsed  = time.time() - started_at
                    cost_val = f"{cost_usd:.6f}" if cost_usd is not None else "none"
                    print(f"[AGENT_DONE] {label} elapsed={elapsed:.1f} cost={cost_val}", flush=True)

        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES and _is_transient(exc):
                continue  # retry
            raise  # non-transient or exhausted retries

        result = "".join(text_parts)

        # Cache the summary so RESUME=1 can restore it without re-running the agent
        state_key = _STATE_FILE_MAP.get(label)
        if state_key and result:
            summary_path = Path(OUT_DIR) / "agent_state" / f"{state_key}_summary.txt"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(result)

        return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"[orchestrator] Starting pipeline  data={DATA_DIR}  model={MODEL}  review={REVIEW_MODEL}", flush=True)

    # ── Phase 1: parallel ───────────────────────────────────────────────
    p1: dict[str, str] = {}
    async with anyio.create_task_group() as tg:
        async def _norm():
            try:
                p1["norm"] = await _run_agent("Normalization Agent", prompts.NORMALIZATION)
            except Exception as _e:
                print(f"[Normalization Agent] ERROR: {_e}", file=sys.stderr, flush=True)
                import traceback; traceback.print_exc()
                raise
        async def _contract():
            if STAGGER_DELAY:
                await anyio.sleep(STAGGER_DELAY)
            try:
                p1["contract"] = await _run_agent("Contract Agent", prompts.CONTRACT)
            except Exception as _e:
                print(f"[Contract Agent] ERROR: {_e}", file=sys.stderr, flush=True)
                import traceback; traceback.print_exc()
                raise
        async def _slack():
            if STAGGER_DELAY:
                await anyio.sleep(STAGGER_DELAY * 2)
            try:
                p1["slack"] = await _run_agent("Context Mining Agent", prompts.SLACK_MINING)
            except Exception as _e:
                print(f"[Context Mining Agent] ERROR: {_e}", file=sys.stderr, flush=True)
                import traceback; traceback.print_exc()
                raise
        tg.start_soon(_norm)
        tg.start_soon(_contract)
        tg.start_soon(_slack)

    norm_summary     = p1["norm"]
    contract_summary = p1["contract"]
    slack_summary    = p1["slack"]

    # ── Phase 2 ─────────────────────────────────────────────────────────
    recon_summary = await _run_agent("Reconciliation Agent", prompts.RECONCILIATION)

    # ── Phase 3: parallel ───────────────────────────────────────────────
    p3: dict[str, str] = {}
    async with anyio.create_task_group() as tg:
        async def _leakage():
            try:
                p3["leakage"] = await _run_agent("Revenue Leakage Agent", prompts.LEAKAGE)
            except Exception as _e:
                print(f"[Revenue Leakage Agent] ERROR: {_e}", file=sys.stderr, flush=True)
                import traceback; traceback.print_exc()
                raise
        async def _compliance():
            if STAGGER_DELAY:
                await anyio.sleep(STAGGER_DELAY)
            try:
                p3["compliance"] = await _run_agent("Compliance Agent", prompts.COMPLIANCE)
            except Exception as _e:
                print(f"[Compliance Agent] ERROR: {_e}", file=sys.stderr, flush=True)
                import traceback; traceback.print_exc()
                raise
        tg.start_soon(_leakage)
        tg.start_soon(_compliance)

    leakage_summary    = p3["leakage"]
    compliance_summary = p3["compliance"]

    # ── Phase 4 ─────────────────────────────────────────────────────────
    invoice_summary = await _run_agent("Invoice Drafting Agent", prompts.INVOICE)

    # ── Phase 5 ─────────────────────────────────────────────────────────
    review_prompt = prompts.review(
        norm_summary, contract_summary, slack_summary,
        recon_summary, leakage_summary, compliance_summary, invoice_summary,
    )
    review_summary = await _run_agent(
        "Review & Alert Agent", review_prompt, max_turns=10, model=REVIEW_MODEL,
    )

    # ── Phase 6: Digest Agent ────────────────────────────────────────────
    _summaries_for_digest = {}
    for _sk in ("leakage_findings", "slack_signals", "compliance_findings",
                "invoice_draft", "reconciled", "work_units"):
        _sp = Path(OUT_DIR) / "agent_state" / f"{_sk}_summary.txt"
        if _sp.exists():
            _summaries_for_digest[_sk] = _sp.read_text()

    digest_raw = await _run_agent(
        "Digest Agent", prompts.digest(_summaries_for_digest), max_turns=1,
    )

    # Parse JSON from agent output and persist to ai_digest.json
    import json as _json, re as _re
    try:
        _raw = digest_raw.strip()
        _raw = _re.sub(r'^```(?:json)?\s*', '', _raw, flags=_re.MULTILINE)
        _raw = _re.sub(r'\s*```$', '', _raw)
        _m = _re.search(r'\{[\s\S]*\}', _raw)
        if _m:
            _digest_data = _json.loads(_m.group())
            _digest_path = Path(OUT_DIR) / "agent_state" / "ai_digest.json"
            _digest_path.parent.mkdir(parents=True, exist_ok=True)
            _digest_path.write_text(_json.dumps(_digest_data, indent=2))
            print(f"[orchestrator] Digest saved -> {_digest_path}", flush=True)
    except Exception as _e:
        print(f"[orchestrator] Digest JSON parse failed: {_e}", file=sys.stderr, flush=True)

    print("[orchestrator] Pipeline complete.", flush=True)

    # Always regenerate the report after Phase 6 so ai_digest.json is included.
    _generate_report_from_state(review_summary, force=True)


def _generate_report_from_state(review_summary: str, force: bool = False) -> None:
    """
    Load all agent state files and call report.generate() directly.
    Always called after Phase 6 (Digest Agent) so ai_digest.json is included.

    force=True skips the "already exists" check so the report is always
    regenerated with the latest digest.
    """
    import glob
    import json
    import re
    from pathlib import Path as _Path

    if not force:
        existing = glob.glob(str(_Path(OUT_DIR) / "audit_*.html"))
        if existing:
            print(f"[orchestrator] Report already at {existing[0]}", flush=True)
            return

    print("[orchestrator] Generating report from state files (digest included)...", flush=True)

    state_dir = _Path(OUT_DIR) / "agent_state"

    def _load(key: str) -> dict:
        p = state_dir / f"{key}.json"
        if p.exists():
            with open(p) as f:
                return json.load(f)
        return {}

    leakage    = _load("leakage_findings")
    compliance = _load("compliance_findings")
    invoice    = _load("invoice_draft")
    slack      = _load("slack_signals")
    work_units = _load("work_units")
    reconciled = _load("reconciled")
    contract   = _load("contract_model")

    # Extract key takeaways from the review agent's text output
    takeaways: list = []
    json_match = re.search(r'\[.*?\]', review_summary, re.DOTALL)
    if json_match:
        try:
            takeaways = json.loads(json_match.group())
        except Exception:
            pass
    if not takeaways:
        # Fall back to numbered lines from the summary text
        for line in review_summary.splitlines():
            line = line.strip().lstrip("0123456789.-) ")
            if len(line) > 20:
                takeaways.append(line)
            if len(takeaways) >= 7:
                break

    # Extract structured insights block from the review agent's output
    executive_insights: dict = {}
    insights_match = re.search(r'<insights_json>\s*(.*?)\s*</insights_json>', review_summary, re.DOTALL)
    if insights_match:
        try:
            executive_insights = json.loads(insights_match.group(1))
        except Exception:
            pass

    from audit.loader import load_all
    from audit.checks import run_all
    from audit.report_builder import generate

    ctx = load_all()
    issues, hours_issues = run_all()

    data_version = _Path(DATA_DIR).name
    out_path = generate(
        issues=issues,
        hours_issues=hours_issues,
        total_entries=work_units.get("total_entries", ctx.get("total_entries", 0)),
        key_takeaways=takeaways,
        data_version=data_version,
        model=REVIEW_MODEL,
        proj_budget_hours=ctx.get("proj_budget_hours", {}),
        proj_budget_cost=ctx.get("proj_budget_cost", {}),
        proj_actual_hours=ctx.get("proj_actual_hours", {}),
        proj_actual_cost=ctx.get("proj_actual_cost", {}),
        leakage_findings=leakage   or None,
        compliance_findings=compliance or None,
        invoice_draft=invoice  or None,
        slack_signals=slack    or None,
        work_units_data=work_units or None,
        reconciled_data=reconciled or None,
        executive_insights=executive_insights or None,
    )
    print(f"[orchestrator] Report written to {out_path}", flush=True)


if __name__ == "__main__":
    import traceback as _tb

    def _print_exc_group(exc: BaseException, depth: int = 0) -> None:
        """Recursively print ExceptionGroup sub-exceptions."""
        indent = "  " * depth
        causes = getattr(exc, "exceptions", None)
        if causes:
            print(f"{indent}ExceptionGroup ({len(causes)} sub-exception(s)): {exc}", file=sys.stderr)
            for i, sub in enumerate(causes, 1):
                print(f"\n{indent}--- Sub-exception {i}/{len(causes)} ---", file=sys.stderr)
                _print_exc_group(sub, depth + 1)
        else:
            _tb.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)

    try:
        anyio.run(main)
    except BaseException as e:
        print(f"\n[orchestrator] Fatal: {e}", file=sys.stderr)
        _print_exc_group(e)
        sys.exit(1)
