"""Slack message confidence bucketing.

Produces three buckets:
  confident        — regex keyword matched → trust regex classification
  ambiguous        — no keyword match but heuristic suggests intent → send to AI
  confident_noise  — short / social / no intent → drop silently
"""
import re

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

_AMBIGUOUS_INTENT_PATTERNS = [
    (r"\bwrap(?:ping)?\s+(?:this|it)\s+up\b", "end-of-day completion intent"),
    (r"\bon\s+it\b", "acknowledging an assigned task"),
    (r"\blooking\s+into\b", "ongoing investigation"),
    (r"\btake\s+care\s+of\s+this\b", "promise of work"),
    (r"\bI(?:'| wi)ll\s+handle\b", "promise of work"),
    (r"\bping\s+me\s+when\b", "handoff expecting async work"),
    (r"\bstill\s+working\s+on\b", "continuing work"),
    (r"\bheads?\s+down\b", "focused work indicator"),
    (r"\bgive\s+me\s+(a\s+)?(sec|min|moment)\b", "active task context"),
]


def _compile(patterns):
    return re.compile("|".join(patterns), re.IGNORECASE)


_WORK = _compile(_WORK_PATTERNS)
_APPROVAL = _compile(_APPROVAL_PATTERNS)
_SCOPE = _compile(_SCOPE_PATTERNS)
_ESCALATION = _compile(_ESCALATION_PATTERNS)


def classify_row_confidence(row: dict) -> dict:
    """Return {confidence, signal_types, reason} for a single Slack row."""
    text = (row.get("text") or row.get("message") or "").strip()
    out = {"confidence": "confident_noise", "signal_types": [], "reason": ""}

    if not text:
        return out

    types = []
    if _WORK.search(text):
        types.append("work_activity")
    if _APPROVAL.search(text):
        types.append("approval")
    if _SCOPE.search(text):
        types.append("scope_change")
    if _ESCALATION.search(text):
        types.append("escalation")

    if types:
        out["confidence"] = "confident"
        out["signal_types"] = types
        return out

    for pat, hint in _AMBIGUOUS_INTENT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            out["confidence"] = "ambiguous"
            out["reason"] = hint
            return out

    return out


def split_confident_and_ambiguous(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split rows into (confident, ambiguous, noise) lists."""
    confident, ambiguous, noise = [], [], []
    for row in rows:
        user = (row.get("user") or "").strip()
        date = (row.get("date") or "").strip()
        text = (row.get("text") or row.get("message") or "").strip()
        if not user or not date or not text:
            noise.append(row)
            continue

        verdict = classify_row_confidence(row)
        enriched = {
            "user": user,
            "date": date,
            "channel": (row.get("channel") or "").strip(),
            "text": text[:300],
            "signal_types": verdict["signal_types"],
            "confidence": verdict["confidence"],
            "reason": verdict["reason"],
        }
        if verdict["confidence"] == "confident":
            confident.append(enriched)
        elif verdict["confidence"] == "ambiguous":
            ambiguous.append(enriched)
        else:
            noise.append(enriched)
    return confident, ambiguous, noise


def apply_ai_classifications(ambiguous: list[dict], ai_verdicts: list[dict]) -> list[dict]:
    """Merge AI verdicts back onto the ambiguous list by (user, date) key."""
    key = lambda r: (r.get("user", ""), r.get("date", ""))
    verdict_by_key = {key(v): v for v in ai_verdicts}

    merged: list[dict] = []
    for row in ambiguous:
        v = verdict_by_key.get(key(row))
        if not v or not v.get("signal_types"):
            continue
        merged.append({
            **row,
            "signal_types": list(v["signal_types"]),
            "ai_rationale": v.get("rationale", ""),
            "confidence": "ai_classified",
        })
    return merged
