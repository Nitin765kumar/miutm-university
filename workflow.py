"""workflow.py - changing an application's status is done in exactly one place."""
from flask import request

import mailer
import site_data
from audit import audit
from db import get_db


def seat_info(conn, course_code):
    """(seats, filled) for a programme. 'Filled' counts Approved and Enrolled applications."""
    seats = conn.execute("SELECT seats FROM courses WHERE code = ?", (course_code,)).fetchone()
    marks = ",".join("?" * len(site_data.SEAT_STATUSES))
    filled = conn.execute(
        f"SELECT COUNT(*) FROM admissions WHERE course_code = ? AND status IN ({marks})",
        (course_code, *site_data.SEAT_STATUSES)).fetchone()[0]
    return (seats["seats"] if seats else 0), filled


def set_status(admission, status, note=None, remarks=None, quiet=False):
    """
    Update status, write the history entry the applicant sees, log it and send the email.
    Returns True if anything changed. Does not commit when quiet=True (caller commits).
    """
    conn = get_db()
    changed = status != admission["status"]
    if remarks is None:
        remarks = admission["remarks"]
    conn.execute("UPDATE admissions SET status = ?, remarks = ?, updated_at = datetime('now') WHERE id = ?",
                 (status, remarks or None, admission["id"]))
    if changed or note:
        conn.execute("INSERT INTO admission_events (admission_id, status, note) VALUES (?,?,?)",
                     (admission["id"], status, note or None))
    if changed:
        audit("status", admission["application_no"], f"{admission['status']} -> {status}", commit=False)
    if not quiet:
        conn.commit()
    if changed:
        mailer.status_changed(admission, status, note, request.url_root)
    return changed


def offer_context(conn, a):
    """Extra facts for the offer letter."""
    course = conn.execute("SELECT * FROM courses WHERE code = ?", (a["course_code"],)).fetchone()
    dates = {m["key"]: m["date"] for m in site_data.current_cycle()["milestones"]}
    return {"course": course, "counselling": dates.get("counselling"), "classes_begin": dates.get("classes"),
            "docs_needed": site_data.required_docs(a["qualification"], a["category"])}
