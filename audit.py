"""audit.py - one line per important action, so staff can see who did what and when."""
from flask import session

from db import get_db


def audit(action, target="", detail="", commit=True):
    if session.get("admin_id"):
        actor, role = session.get("admin_name", "staff"), session.get("admin_role", "staff")
    elif session.get("student_id"):
        actor, role = session.get("student_email", "student"), "student"
    else:
        actor, role = "visitor", "visitor"
    conn = get_db()
    conn.execute("INSERT INTO audit_log (actor, role, action, target, detail) VALUES (?,?,?,?,?)",
                 (actor, role, action, str(target)[:80], str(detail)[:300]))
    if commit:
        conn.commit()
