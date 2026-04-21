"""
Context Mining Agent (Slack) logic.

Confident signals are classified by regex in slack_classifier. Ambiguous
messages are surfaced to the agent for AI-reasoned classification.
"""
from collections import defaultdict
from audit.loader import load_all, load_csv, discover_csv_files


def extract_slack_signals(slack_rows: list[dict], ts_days: set[tuple]) -> dict:
    """
    Classify Slack messages and cross-reference against timesheet days.

    Returns confident signals (regex-matched) plus an `ambiguous_messages`
    list that the Context Mining agent can submit to classify_ambiguous_messages
    for AI judgment.
    """
    from audit.tools.slack_classifier import split_confident_and_ambiguous

    confident, ambiguous, _noise = split_confident_and_ambiguous(slack_rows)

    signals: list[dict] = []
    work_without_timesheet: list = []
    for c in confident:
        has_ts = (c["user"], c["date"]) in ts_days
        sig = {
            "user":          c["user"],
            "date":          c["date"],
            "channel":       c["channel"],
            "text":          c["text"],
            "signal_types":  c["signal_types"],
            "has_timesheet": has_ts,
        }
        signals.append(sig)
        if "work_activity" in c["signal_types"] and not has_ts:
            work_without_timesheet.append(sig)

    type_counts: dict[str, int] = defaultdict(int)
    for s in signals:
        for t in s["signal_types"]:
            type_counts[t] += 1

    by_user: dict[str, int] = defaultdict(int)
    for s in work_without_timesheet:
        by_user[s["user"]] += 1

    return {
        "signals":                signals,
        "total_signals":          len(signals),
        "signal_type_counts":     dict(type_counts),
        "work_without_timesheet": work_without_timesheet,
        "unlogged_work_count":    len(work_without_timesheet),
        "unlogged_by_user":       dict(by_user),
        "ambiguous_messages":     ambiguous,
        "ambiguous_count":        len(ambiguous),
    }


def run_slack_mining() -> dict:
    """Load all data and run Slack signal extraction."""
    ctx = load_all()
    ts  = ctx["ts"]

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
            "ambiguous_messages":    [],
            "ambiguous_count":       0,
            "note":                  "No Slack data file found",
        }

    slack_rows = load_csv(slack_file["path"])
    ts_days    = {(r.get("user", "").strip(), r.get("date", "").strip()) for r in ts}

    return extract_slack_signals(slack_rows, ts_days)
