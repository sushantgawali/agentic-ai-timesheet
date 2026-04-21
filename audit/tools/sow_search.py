"""SOW document section lookup used by the Contract agent to re-investigate
missing or ambiguous contract data. Pure functions — no I/O."""
import re


def _best_matching_sow(sow_documents: list[dict], project: str) -> dict | None:
    p_lower = (project or "").lower().strip()
    if not p_lower:
        return None
    for doc in sow_documents:
        if (doc.get("project_name") or "").lower() == p_lower:
            return doc
    for doc in sow_documents:
        if p_lower in (doc.get("project_name") or "").lower():
            return doc
    return None


def find_sow_section(sow_documents: list[dict], query: str, project: str) -> dict:
    """Return the first text window in the matching SOW containing `query`."""
    doc = _best_matching_sow(sow_documents, project)
    if not doc:
        return {"found": False, "excerpt": "", "source_filename": None}

    text = doc.get("text", "") or ""
    q = (query or "").strip()
    if not q:
        return {"found": False, "excerpt": "", "source_filename": doc.get("filename")}

    m = re.search(re.escape(q), text, re.IGNORECASE)
    if not m:
        return {"found": False, "excerpt": "", "source_filename": doc.get("filename")}

    start = max(0, m.start() - 120)
    end = min(len(text), m.end() + 240)
    return {
        "found": True,
        "excerpt": text[start:end].strip(),
        "source_filename": doc.get("filename"),
    }


_RATE_LINE_PAT = re.compile(
    r"(?P<name>[A-Z][A-Za-z.\- ]{1,40}?)\s*[:\-]\s*\$?\s*(?P<rate>\d{1,4}(?:\.\d{1,2})?)\s*(?:/\s*hr|per\s+hour|/hour|hr)",
    re.IGNORECASE,
)


def find_rate_for_member(sow_documents: list[dict], member_name: str, project: str) -> dict:
    """Scan the raw SOW text for a rate line matching `member_name`."""
    doc = _best_matching_sow(sow_documents, project)
    if not doc or not member_name:
        return {"found": False, "rate": None, "evidence": "", "source_filename": None}

    text = doc.get("text", "") or ""
    target = member_name.lower().strip()

    for m in _RATE_LINE_PAT.finditer(text):
        name = m.group("name").lower().strip()
        if target in name or name in target:
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 120)
            return {
                "found": True,
                "rate": float(m.group("rate")),
                "evidence": text[start:end].strip(),
                "source_filename": doc.get("filename"),
            }

    return {"found": False, "rate": None, "evidence": "", "source_filename": doc.get("filename")}
