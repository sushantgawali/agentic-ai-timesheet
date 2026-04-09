"""
Context Mining Agent (Slack) logic.

Classifies raw Slack messages into signal types:
  work_activity  — evidence of work done but potentially not logged
  approval       — verbal/written go-ahead (overtime, scope change, etc.)
  scope_change   — informal requests to do extra work
  escalation     — urgent / production issues that may have generated unlogged effort
"""
import re
from collections import defaultdict
from audit.loader import load_all, load_csv, discover_csv_files

# ---------------------------------------------------------------------------
# Signal keyword patterns
# ---------------------------------------------------------------------------

_WORK_PATTERNS = [
    r"\bfixed\b", r"\bdeployed\b", r"\bpushed\b", r"\bmerged\b",
    r"\bimplemented\b", r"\bcompleted\b", r"\bfinished\b",
    r"\bupdated\b", r"\brebuilt\b", r"\brefactored\b", r"\bpatched\b",
    r"\bhotfix\b", r"\bbugfix\b", r"\bworked on\b", r"\bwrote\b",
    r"\bbuilt\b", r"\bcreated\b", r"\bset up\b", r"\bconfigured\b",
    r"\binvestigated\b", r"\bdebugged\b", r"\btested\b", r"\breviewed\b",
    r"\blast night\b", r"\bover the weekend\b", r"\bearly this morning\b",
    r"\bjust finished\b", r"\bjust deployed\b", r"\bjust pushed\b",
    r"\byesterday\b.*\b(worked|fixed|deployed|finished)\b",
]
_APPROVAL_PATTERNS = [
    r"\bgo ahead\b", r"\bapproved\b", r"\bsign(?:ed)? off\b",
    r"\bgreen light\b", r"\bLGTM\b", r"\bproceed\b", r"\bconfirmed\b",
    r"\bauthori[sz]ed\b", r"\bgiven approval\b", r"\bok(?:ay)? to proceed\b",
    r"\byou're good to go\b",
]
_SCOPE_PATTERNS = [
    r"\bcan you also\b", r"\bwhile you'?re at it\b", r"\badditional(?:ly)?\b",
    r"\bextra\b.{0,30}\b(feature|work|task|integration|requirement)\b",
    r"\bnew requirement\b", r"\bchange request\b", r"\bscope change\b",
    r"\bbeyond the original\b", r"\bnot in the original scope\b",
    r"\bchange order\b", r"\bCR\b",
    r"\b(also|additionally).{0,30}\b(handle|implement|add|build|fix)\b",
]
_ESCALATION_PATTERNS = [
    r"\burgent\b", r"\bproduction (bug|issue|down|problem|incident)\b",
    r"\bcritical (bug|issue|problem)\b", r"\bp0\b", r"\bsev\s?[01]\b",
    r"\bblocking\b", r"\bescalat(ion|ed)\b",
    r"\b(site|service|system|api)\s+is\s+(down|broken|failing)\b",
    r"\boutage\b",
]

_COMPILED: dict = {}


def _pat(patterns: list[str]) -> re.Pattern:
    key = tuple(patterns)
    if key not in _COMPILED:
        _COMPILED[key] = re.compile("|".join(patterns), re.IGNORECASE)
    return _COMPILED[key]


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_slack_signals(slack_rows: list[dict], ts_days: set[tuple]) -> dict:
    """
    Classify Slack messages and cross-reference against timesheet days.

    Args:
        slack_rows: raw Slack CSV rows (must have user, date, text columns)
        ts_days:    set of (user, date) tuples that have at least one timesheet entry

    Returns signal summary including unlogged-work signals.
    """
    work_pat       = _pat(_WORK_PATTERNS)
    approval_pat   = _pat(_APPROVAL_PATTERNS)
    scope_pat      = _pat(_SCOPE_PATTERNS)
    escalation_pat = _pat(_ESCALATION_PATTERNS)

    signals: list[dict]            = []
    work_without_timesheet: list   = []

    for row in slack_rows:
        user    = row.get("user", "").strip()
        date    = row.get("date", "").strip()
        text    = (row.get("text") or row.get("message") or "").strip()
        channel = row.get("channel", "").strip()

        if not text or not user or not date:
            continue

        types: list[str] = []
        if work_pat.search(text):
            types.append("work_activity")
        if approval_pat.search(text):
            types.append("approval")
        if scope_pat.search(text):
            types.append("scope_change")
        if escalation_pat.search(text):
            types.append("escalation")

        if not types:
            continue

        has_ts = (user, date) in ts_days
        sig = {
            "user":         user,
            "date":         date,
            "channel":      channel,
            "text":         text[:300],
            "signal_types": types,
            "has_timesheet": has_ts,
        }
        signals.append(sig)

        if "work_activity" in types and not has_ts:
            work_without_timesheet.append(sig)

    # Count by type
    type_counts: dict[str, int] = defaultdict(int)
    for s in signals:
        for t in s["signal_types"]:
            type_counts[t] += 1

    # Per-user unlogged summary
    by_user: dict[str, int] = defaultdict(int)
    for s in work_without_timesheet:
        by_user[s["user"]] += 1

    return {
        "signals":               signals,
        "total_signals":         len(signals),
        "signal_type_counts":    dict(type_counts),
        "work_without_timesheet": work_without_timesheet,
        "unlogged_work_count":   len(work_without_timesheet),
        "unlogged_by_user":      dict(by_user),
    }


def run_slack_mining() -> dict:
    """Load all data and run Slack signal extraction."""
    ctx = load_all()
    ts  = ctx["ts"]

    # Need raw Slack rows with text column
    files     = discover_csv_files()
    slack_file = next((f for f in files if f["role"] == "slack"), None)

    if not slack_file:
        return {
            "signals":               [],
            "total_signals":         0,
            "signal_type_counts":    {},
            "work_without_timesheet": [],
            "unlogged_work_count":   0,
            "unlogged_by_user":      {},
            "note":                  "No Slack data file found",
        }

    slack_rows = load_csv(slack_file["path"])
    ts_days    = {(r.get("user", "").strip(), r.get("date", "").strip()) for r in ts}

    return extract_slack_signals(slack_rows, ts_days)
