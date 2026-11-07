"""notify.py - in-app notifications for students (the bell in the header and the notifications page)."""
from db import get_db


def notify(student_id, title, body="", link=None, kind="info"):
    """Add a notification inside the caller's transaction. Does nothing for applicants without an account."""
    if not student_id:
        return
    get_db().execute("INSERT INTO notifications (student_id, title, body, link, kind) VALUES (?,?,?,?,?)",
                     (student_id, title[:140], body[:600], link, kind))


def unread_count(student_id):
    return get_db().execute("SELECT COUNT(*) FROM notifications WHERE student_id = ? AND is_read = 0",
                            (student_id,)).fetchone()[0]
