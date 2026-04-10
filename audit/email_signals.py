"""
Email signal parser — extracts structured billing signals from categorised email rows.

Parsed signals are consumed by checks.py to:
  - Exempt approved extra-time from CHECK-11 (weekend) and CHECK-14 (public holiday)
  - Extend project end dates from date_extension emails (CHECK-5 archived project)
  - Add client holidays as CHECK-17 (client holiday billing)
  - Flag low-hour users from escalation emails as CHECK-18
  - Supplement formal assignments from assignment emails (CHECK-4 unassigned project)
"""
from __future__ import annotations

import re
from collections import defaultdict


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def parse_email_signals(email_rows: list[dict]) -> dict:
    """
    Parse all email categories into structured billing signals.

    Returns:
        {
            "extra_time_approvals": set of (user_lower, date_str)
                — (user, date) pairs approved for overtime/weekend work.

            "extended_end_dates": dict {project_lower: new_end_date_str}
                — projects whose SOW end date has been extended via email.

            "client_holiday_dates": set of date_str
                — dates declared as client-side no-billing holidays.

            "escalations": list of {user, project, expected_hrs, actual_hrs, date}
                — low-hour escalations raised by client/management.

            "email_assignments": set of (user_lower, project_lower)
                — (user, project) pairs confirmed via onboarding email.
        }
    """
    extra_time_approvals: set  = set()
    extended_end_dates:   dict = {}
    client_holiday_dates: set  = set()
    escalations:          list = []
    email_assignments:    set  = set()

    for email in email_rows:
        cat     = email.get("category", "")
        subject = email.get("subject", "")
        date    = email.get("date", "")
        body    = _strip_html(email.get("body_html", ""))

        if cat == "extra_time":
            # Subject: "Approval: Extra time for {User} on {Project} - {Date}"
            m = re.search(
                r"Approval:\s*Extra time for\s+(.+?)\s+on\s+(.+?)\s+-\s+(\d{4}-\d{2}-\d{2})",
                subject, re.IGNORECASE,
            )
            if m:
                user_raw, _proj, approved_date = m.group(1), m.group(2), m.group(3)
                extra_time_approvals.add((user_raw.lower().replace(" ", "."), approved_date))
            else:
                # Fall back: use email date + any user mentioned in body
                users_in_body = re.findall(r"\b([A-Z][a-z]+\.[A-Z][a-z]+)\b", body)
                for u in users_in_body:
                    extra_time_approvals.add((u.lower(), date))

        elif cat == "date_extension":
            # Subject: "Date Extension: {Project} - revised end date {Date}"
            m = re.search(
                r"Date Extension:\s*(.+?)\s+-\s*revised end date\s+(\d{4}-\d{2}-\d{2})",
                subject, re.IGNORECASE,
            )
            if m:
                proj_raw, new_end = m.group(1).strip(), m.group(2)
                extended_end_dates[proj_raw.lower()] = new_end
            else:
                # Fall back: parse revised end date from body
                m2 = re.search(r"Revised End Date\s+(\d{4}-\d{2}-\d{2})", body)
                if m2:
                    # Try to get project from subject remainder
                    proj_guess = re.sub(r"Date Extension:\s*", "", subject, flags=re.IGNORECASE).strip()
                    if proj_guess:
                        extended_end_dates[proj_guess.lower()] = m2.group(1)

        elif cat == "client_holiday":
            # Subject: "Holiday Notice: {Name} ({Date}) - {Client}"
            m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", subject)
            if m:
                client_holiday_dates.add(m.group(1))
            elif date:
                client_holiday_dates.add(date)

        elif cat == "escalation":
            # Subject: "Concern: Low hours for {User} on {Project}"
            m = re.search(
                r"Concern:\s*Low hours for\s+(.+?)\s+on\s+(.+)",
                subject, re.IGNORECASE,
            )
            if m:
                user_raw, proj_raw = m.group(1).strip(), m.group(2).strip()
                expected = _parse_hours(body, r"Expected\s+([\d.]+)\s*hrs")
                actual   = _parse_hours(body, r"Actual\s+([\d.]+)\s*hrs")
                escalations.append({
                    "user":         user_raw,
                    "user_lower":   user_raw.lower().replace(" ", "."),
                    "project":      proj_raw,
                    "project_lower": proj_raw.lower(),
                    "expected_hrs": expected,
                    "actual_hrs":   actual,
                    "date":         date,
                })

        elif cat == "assignment":
            # Subject: "Fwd: Team onboarding - {Project}"
            # Body table: Name | Project | Start Date rows
            # Extract all (Name, Project) pairs from the table rows
            # Pattern after "Name Project Start Date": repeated "Name Project Date"
            table_section = re.sub(r".*Name Project Start Date", "", body, flags=re.DOTALL)
            date_pattern = r"\d{4}-\d{2}-\d{2}"
            rows = re.split(date_pattern, table_section)
            dates_found = re.findall(date_pattern, table_section)
            for row_text, row_date in zip(rows, dates_found):
                # Each row_text should end with "Name Project" before the date
                tokens = row_text.strip().split()
                if len(tokens) >= 2:
                    # Heuristic: last token(s) form the project, first token(s) form the name
                    # Try to match known projects by presence of capital words
                    # Simplest: take last N tokens as project (up to next match) — use subject project as fallback
                    name_tokens = [t for t in tokens if t[0].isupper()]
                    if name_tokens:
                        user_name = name_tokens[0].lower().replace(" ", ".")
                        # Get project from all following capitalised words
                        proj_tokens = name_tokens[1:]
                        proj_str = " ".join(proj_tokens).lower() if proj_tokens else ""
                        if proj_str:
                            email_assignments.add((user_name, proj_str))
                        # Also try project from subject
                        subj_m = re.search(r"Team onboarding - (.+)", subject, re.IGNORECASE)
                        if subj_m:
                            email_assignments.add((user_name, subj_m.group(1).strip().lower()))

    return {
        "extra_time_approvals": extra_time_approvals,
        "extended_end_dates":   extended_end_dates,
        "client_holiday_dates": client_holiday_dates,
        "escalations":          escalations,
        "email_assignments":    email_assignments,
    }


def _parse_hours(text: str, pattern: str) -> float:
    m = re.search(pattern, text, re.IGNORECASE)
    try:
        return float(m.group(1)) if m else 0.0
    except (ValueError, AttributeError):
        return 0.0
