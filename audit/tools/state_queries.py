"""Query helpers over persisted agent state, exposed to the Review agent as
callable MCP tools so it can investigate cross-cutting patterns instead of
restating upstream summaries."""

_UNLOGGED_HOURS_PER_SIGNAL = 2.0


def filter_leakage_findings(
    leakage: dict,
    user: str | None = None,
    project: str | None = None,
    finding_type: str | None = None,
) -> dict:
    findings = leakage.get("findings", []) if leakage else []
    u = (user or "").lower().strip()
    p = (project or "").lower().strip()
    t = (finding_type or "").lower().strip()

    matched = []
    for f in findings:
        if u and (f.get("user") or "").lower() != u:
            continue
        if p and (f.get("project") or "").lower() != p:
            continue
        if t and (f.get("type") or "").lower() != t:
            continue
        matched.append(f)

    total = round(sum(float(f.get("estimated_impact") or 0) for f in matched), 2)
    return {
        "match_count": len(matched),
        "findings": matched,
        "total_impact": total,
    }


def filter_unlogged_signals(slack: dict, user: str | None = None, project: str | None = None) -> dict:
    signals = slack.get("work_without_timesheet", []) if slack else []
    u = (user or "").lower().strip()
    p = (project or "").lower().strip()

    matched = []
    for s in signals:
        if u and (s.get("user") or "").lower() != u:
            continue
        if p and p not in (s.get("channel") or "").lower():
            continue
        matched.append(s)

    return {"match_count": len(matched), "signals": matched}


def compound_exposure(
    leakage: dict,
    slack: dict,
    user: str,
    project: str | None = None,
    hourly_rate_assumption: float = 100.0,
) -> dict:
    lk = filter_leakage_findings(leakage, user=user, project=project)
    sl = filter_unlogged_signals(slack, user=user, project=project)

    estimated_unlogged = round(
        sl["match_count"] * _UNLOGGED_HOURS_PER_SIGNAL * hourly_rate_assumption, 2
    )
    return {
        "user": user,
        "project": project,
        "leakage_impact": lk["total_impact"],
        "leakage_finding_count": lk["match_count"],
        "unlogged_signal_count": sl["match_count"],
        "estimated_unlogged_impact": estimated_unlogged,
        "hours_per_signal_assumed": _UNLOGGED_HOURS_PER_SIGNAL,
        "rate_assumed": hourly_rate_assumption,
        "total_exposure": round(lk["total_impact"] + estimated_unlogged, 2),
    }
