"""workflow.py - everything that changes an application's status goes through here."""
from flask import request, session, url_for

import mailer
import notify
import site_data
from audit import audit
from db import get_db


def actor_name():
    if session.get("admin_id"):
        return session.get("admin_name", "staff")
    if session.get("student_id"):
        return session.get("student_email", "student")
    return "system"


def seat_info(conn, course_code):
    """(seats, held) for a programme. 'Held' counts the statuses that hold a seat."""
    row = conn.execute("SELECT seats FROM courses WHERE code = ?", (course_code,)).fetchone()
    marks = ",".join("?" * len(site_data.SEAT_STATUSES))
    held = conn.execute(f"SELECT COUNT(*) FROM admissions WHERE course_code = ? AND status IN ({marks})",
                        (course_code, *site_data.SEAT_STATUSES)).fetchone()[0]
    return (row["seats"] if row else 0), held


def set_status(admission, status, note=None, remarks=None, quiet=False, reason=None):
    """
    Move an application to a new status: write the history (with who and from what), notify the student in the
    app and by email, free the seat for the next waitlisted applicant, and log it.
    Returns True if the status changed. With quiet=True the caller commits.
    """
    conn = get_db()
    prev = admission["status"]
    changed = status != prev
    if remarks is None:
        remarks = admission["remarks"]
    conn.execute(
        "UPDATE admissions SET status = ?, remarks = ?, updated_at = datetime('now'), "
        "submitted_at = CASE WHEN ? = 'Submitted' AND submitted_at IS NULL THEN datetime('now') ELSE submitted_at END, "
        "rejection_reason = CASE WHEN ? = 'Rejected' THEN ? ELSE rejection_reason END WHERE id = ?",
        (status, remarks or None, status, status, reason or note, admission["id"]))
    if changed or note:
        conn.execute("INSERT INTO admission_events (admission_id, status, previous_status, changed_by, note) VALUES (?,?,?,?,?)",
                     (admission["id"], status, prev if changed else None, actor_name(), note or None))
    if changed:
        audit("status", admission["application_no"], f"{prev} -> {status}", commit=False)
        link = url_for("student.application", application_no=admission["application_no"])
        notify.notify(admission["student_id"], f"{admission['course_code']}: {status}",
                      (site_data.STATUS_HELP.get(status, "") + (f" {note}" if note else "")).strip(), link, "status")
        if prev in site_data.SEAT_STATUSES and status not in site_data.SEAT_STATUSES:
            promote_waitlist(conn, admission["course_code"])
    if not quiet:
        conn.commit()
    if changed:
        mailer.status_changed(admission, status, note, request.url_root)
    return changed


def promote_waitlist(conn, course_code):
    """When a seat frees up, select the best-ranked waitlisted applicant. Returns how many were promoted."""
    promoted = 0
    while True:
        seats, held = seat_info(conn, course_code)
        if seats - held <= 0:
            return promoted
        row = conn.execute(
            "SELECT * FROM admissions WHERE course_code = ? AND status = 'Waitlisted' "
            "ORDER BY CASE WHEN merit_rank IS NULL THEN 1 ELSE 0 END, merit_rank, created_at, id LIMIT 1",
            (course_code,)).fetchone()
        if row is None:
            return promoted
        set_status(row, "Selected", note="A seat opened up and you were selected from the waiting list.", quiet=True)
        promoted += 1


def run_merit(conn, course_code):
    """
    Rank every live application for the programme by marks (then by who applied first), store the rank and
    score, select as many of the waiting applicants as there are free seats, and waitlist the rest.
    Returns (selected, waitlisted).
    """
    live = conn.execute(
        "SELECT * FROM admissions WHERE course_code = ? AND status NOT IN ('Rejected', 'Cancelled', 'Payment Pending') "
        "ORDER BY percentage DESC, created_at ASC, id ASC", (course_code,)).fetchall()
    for i, row in enumerate(live, 1):
        conn.execute("UPDATE admissions SET merit_rank = ?, merit_score = ? WHERE id = ?", (i, row["percentage"], row["id"]))
    seats, held = seat_info(conn, course_code)
    free = max(0, seats - held)
    pool = [r for r in live if r["status"] in site_data.REVIEW_POOL]
    selected = waitlisted = 0
    for r in pool:
        if selected < free:
            set_status(r, "Selected", note="Selected in the merit list.", quiet=True)
            selected += 1
        else:
            set_status(r, "Waitlisted", note="All seats are filled. You are on the waiting list.", quiet=True)
            waitlisted += 1
    return selected, waitlisted


def timeline(a, required, docs):
    """The stages of an application for the student, each 'done', 'current' or 'todo'."""
    have = {d["doc_type"]: d["status"] for d in docs}
    uploaded = all(n in have for n in required)
    verified = bool(required) and all(have.get(n) == "Verified" for n in required)
    st = a["status"]
    stages = [
        ("Registration", True),
        ("Application filled", True),
        ("Documents uploaded", uploaded),
        ("Payment completed", a["payment_status"] in ("Paid", "Waived", "Refunded")),
        ("Application submitted", st != "Payment Pending" and st != "Cancelled" or bool(a["submitted_at"])),
        ("Document verification", verified),
        ("Merit evaluation", a["merit_rank"] is not None or st in ("Selected", "Admission Fee Pending", "Approved", "Admission Confirmed")),
        ("Admission approval", st in ("Approved", "Admission Confirmed")),
        ("Admission confirmed", st == "Admission Confirmed"),
    ]
    out, current_set = [], False
    for label, done in stages:
        if done:
            out.append({"label": label, "state": "done"})
        elif not current_set and st not in site_data.CLOSED:
            out.append({"label": label, "state": "current"})
            current_set = True
        else:
            out.append({"label": label, "state": "todo"})
    return out


def offer_context(conn, a):
    """Extra facts for the admission letter."""
    course = conn.execute("SELECT * FROM courses WHERE code = ?", (a["course_code"],)).fetchone()
    dates = {m["key"]: m["date"] for m in site_data.current_cycle()["milestones"]}
    return {"course": course, "counselling": dates.get("counselling"), "classes_begin": dates.get("classes"),
            "docs_needed": site_data.required_docs(a["qualification"], a["category"])}
