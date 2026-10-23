"""
admin.py - the staff area under /admin.

Two roles:
  admin     can do everything
  reviewer  can review applications and documents, answer messages and tickets, view reports;
            cannot delete, run merit lists, manage content or staff, or download backups.
Every page except sign-in needs a signed-in, active staff account, and every change is a POST
with a CSRF token. Important actions are written to the activity log.
"""
import csv
import io
from urllib.parse import urlparse

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
import security
import site_data
import validators
import workflow
from audit import audit
from db import get_db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PAGE_SIZE = 20
_DUMMY_HASH = generate_password_hash("not-a-real-password")
admin_only = security.roles_required("admin")


def _safe_next(target):
    """Only follow relative paths inside this site."""
    if not target:
        return None
    parts = urlparse(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@admin_bp.context_processor
def inject_admin_globals():
    staff = security.current_staff()
    if staff is None:
        return {}
    conn = get_db()
    return {
        "staff": staff,
        "unread_count": conn.execute("SELECT COUNT(*) FROM contact_messages WHERE is_read = 0").fetchone()[0],
        "open_tickets": conn.execute("SELECT COUNT(*) FROM tickets WHERE status IN ('Open','In progress')").fetchone()[0],
        "docs_waiting": conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'Uploaded'").fetchone()[0],
        "staff_pending": conn.execute("SELECT COUNT(*) FROM users WHERE approved = 0").fetchone()[0],
    }


# ---------------------------------------------------------------------------
# Sign in / out
# ---------------------------------------------------------------------------
@admin_bp.route("")
def home():
    return redirect(url_for("admin.dashboard" if security.current_staff() else "admin.login"))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if security.current_staff():
        return redirect(url_for("admin.dashboard"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()[:60]
        if (security.too_many("login-ip", security.client_ip(), 10, 900)
                or security.too_many("login-user", username, 6, 900)):
            abort(429)
        user = get_db().execute("SELECT * FROM users WHERE lower(username) = ?", (username,)).fetchone()
        ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, request.form.get("password") or "")
        if user and ok and not user["approved"]:
            error = "Your registration is waiting for an administrator to approve it. Try again later."
        elif user and ok and not user["is_active"]:
            error = "This account is disabled. Ask an administrator to enable it."
        elif user and ok:
            next_url = _safe_next(session.pop("next", None))
            security.sign_in_staff(user, remember=request.form.get("remember") == "1")
            conn = get_db()
            conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user["id"],))
            audit("login", user["username"], commit=False)
            conn.commit()
            return redirect(next_url or url_for("admin.dashboard"))
        if error is None:
            audit("login failed", username or "(blank)")
            error = "Wrong username or password."
    return render_template("admin/login.html", error=error)


@admin_bp.post("/logout")
def logout():
    security.sign_out_staff()
    flash("You have signed out of the staff area.", "info")
    return redirect(url_for("admin.login"))


@admin_bp.route("/register", methods=["GET", "POST"])
def register():
    """Staff can ask for an account. It stays disabled until an administrator approves it."""
    if security.current_staff():
        return redirect(url_for("admin.dashboard"))
    code = site_data.staff_signup_code()
    values, errors, done = {}, {}, False
    if request.method == "POST":
        if security.too_many("staff-register", security.client_ip(), 5, 3600):
            abort(429)
        if request.form.get("website"):
            return redirect(url_for("admin.login"))
        values, errors = validators.validate_staff_registration(request.form, code)
        conn = get_db()
        if not errors and conn.execute("SELECT 1 FROM users WHERE lower(username) = ?", (values["username"],)).fetchone():
            errors["username"] = "That username is taken."
        if not errors:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, email, role, is_active, approved) VALUES (?,?,?,?, 'reviewer', 0, 0)",
                (values["username"], generate_password_hash(request.form["password"]), values["full_name"], values["email"]))
            audit("staff registration", values["username"], values["email"], commit=False)
            conn.commit()
            done = True
        elif errors:
            return render_template("admin/register.html", values=values, errors=errors, done=False, code_needed=bool(code)), 422
    return render_template("admin/register.html", values=values, errors=errors, done=done, code_needed=bool(code))


@admin_bp.post("/staff/<int:uid>/approve")
@admin_only
def staff_approve(uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ? AND approved = 0", (uid,)).fetchone()
    if user is None:
        abort(404)
    role = request.form.get("role") if request.form.get("role") in site_data.ROLES else "reviewer"
    conn.execute("UPDATE users SET approved = 1, is_active = 1, role = ? WHERE id = ?", (role, uid))
    audit("staff approved", user["username"], role, commit=False)
    conn.commit()
    flash(f"{user['username']} can now sign in as {site_data.ROLES[role].lower()}.", "success")
    return redirect(url_for("admin.staff_list"))


@admin_bp.post("/staff/<int:uid>/reject")
@admin_only
def staff_reject(uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ? AND approved = 0", (uid,)).fetchone()
    if user is None:
        abort(404)
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    audit("staff rejected", user["username"], commit=False)
    conn.commit()
    flash(f"Registration from {user['username']} was declined and removed.", "success")
    return redirect(url_for("admin.staff_list"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin_bp.get("/dashboard")
@security.login_required
def dashboard():
    conn = get_db()
    counts = {s: 0 for s in site_data.STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM admissions GROUP BY status"):
        counts[row["status"]] = row["n"]
    marks = ",".join("?" * len(site_data.SEAT_STATUSES))
    by_course = conn.execute(
        f"""SELECT c.name, c.code, c.seats, COUNT(a.id) AS applied,
                   SUM(CASE WHEN a.status IN ({marks}) THEN 1 ELSE 0 END) AS filled
            FROM courses c LEFT JOIN admissions a ON a.course_code = c.code
            GROUP BY c.id ORDER BY c.sort_order""", site_data.SEAT_STATUSES).fetchall()
    return render_template(
        "admin/dashboard.html", counts=counts, total=sum(counts.values()), by_course=by_course,
        latest=conn.execute("SELECT * FROM admissions ORDER BY id DESC LIMIT 6").fetchall(),
        messages=conn.execute("SELECT * FROM contact_messages ORDER BY id DESC LIMIT 4").fetchall(),
        students=conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        drafts=conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
        state=site_data.admissions_state(), opens_closes=site_data.admission_window())


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def _like(term):
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filtered_query(args):
    where, params = [], []
    search = (args.get("q") or "").strip()[:60]
    status = (args.get("status") or "").strip()
    course = (args.get("course") or "").strip()
    if search:
        where.append("(application_no LIKE ? ESCAPE '\\' OR full_name LIKE ? ESCAPE '\\' "
                     "OR phone LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')")
        params += [_like(search)] * 4
    if status in site_data.STATUSES:
        where.append("status = ?")
        params.append(status)
    else:
        status = ""
    if course:
        where.append("course_code = ?")
        params.append(course)
    return (" WHERE " + " AND ".join(where)) if where else "", params, {"q": search, "status": status, "course": course}


@admin_bp.get("/applications")
@security.login_required
def applications():
    conn = get_db()
    clause, params, filters = _filtered_query(request.args)
    total = conn.execute(f"SELECT COUNT(*) FROM admissions{clause}", params).fetchone()[0]
    pages = max(1, -(-total // PAGE_SIZE))
    try:
        page = min(max(1, int(request.args.get("page", 1))), pages)
    except ValueError:
        page = 1
    rows = conn.execute(f"SELECT * FROM admissions{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                        params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    courses = conn.execute("SELECT code, name FROM courses ORDER BY sort_order").fetchall()
    return render_template("admin/applications.html", rows=rows, total=total, page=page, pages=pages,
                           filters=filters, courses=courses, statuses=site_data.STATUSES)


def _cell(value):
    """Stop spreadsheet programs from running text that starts with = + - @ as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@admin_bp.get("/applications/export.csv")
@security.login_required
def export_csv():
    conn = get_db()
    clause, params, _ = _filtered_query(request.args)
    rows = conn.execute(f"SELECT * FROM admissions{clause} ORDER BY id DESC", params).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Application no", "Submitted (UTC)", "Status", "Name", "Father", "Mother", "Gender", "Date of birth",
                "Email", "Phone", "Category", "Nationality", "Qualification", "Percentage", "Programme", "Address",
                "City", "State", "PIN"])
    for r in rows:
        w.writerow([_cell(x) for x in (
            r["application_no"], r["created_at"], r["status"], r["full_name"], r["father_name"], r["mother_name"],
            r["gender"], r["dob"], r["email"], r["phone"], r["category"], r["nationality"], r["qualification"],
            r["percentage"], r["course_name"], r["address"], r["city"], r["state"], r["pincode"])])
    audit("export csv", f"{len(rows)} rows")
    return Response(out.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=miutm-applications.csv", "Cache-Control": "no-store"})


def _get_application(admission_id):
    row = get_db().execute("SELECT * FROM admissions WHERE id = ?", (admission_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@admin_bp.get("/applications/<int:admission_id>")
@security.login_required
def application(admission_id):
    a = _get_application(admission_id)
    conn = get_db()
    seats, filled = workflow.seat_info(conn, a["course_code"])
    return render_template(
        "admin/application.html", a=a, statuses=site_data.STATUSES, seats=seats, filled=filled,
        events=conn.execute("SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id DESC", (admission_id,)).fetchall(),
        docs=conn.execute("SELECT id, doc_type, filename, size, status, note, uploaded_at FROM documents WHERE admission_id = ? ORDER BY id",
                          (admission_id,)).fetchall(),
        required=site_data.required_docs(a["qualification"], a["category"]), doc_statuses=site_data.DOC_STATUSES,
        owner=conn.execute("SELECT full_name, email FROM students WHERE id = ?", (a["student_id"],)).fetchone() if a["student_id"] else None)


@admin_bp.get("/applications/<int:admission_id>/print")
@security.login_required
def print_application(admission_id):
    a = _get_application(admission_id)
    return render_template("print_page.html", a=a, partial="partials/_application_sheet.html",
                           back_url=url_for("admin.application", admission_id=admission_id))


@admin_bp.get("/applications/<int:admission_id>/offer")
@security.login_required
def offer_letter(admission_id):
    a = _get_application(admission_id)
    if a["status"] not in ("Approved", "Enrolled"):
        flash("An offer letter is only available for Approved or Enrolled applications.", "info")
        return redirect(url_for("admin.application", admission_id=admission_id))
    return render_template("print_page.html", a=a, partial="partials/_offer_letter.html",
                           back_url=url_for("admin.application", admission_id=admission_id),
                           **workflow.offer_context(get_db(), a))


@admin_bp.post("/applications/<int:admission_id>/status")
@security.login_required
def update_status(admission_id):
    a = _get_application(admission_id)
    values, errors = validators.validate_status_update(request.form)
    if errors:
        flash(errors["status"], "danger")
        return redirect(url_for("admin.application", admission_id=admission_id))
    conn = get_db()
    seats, filled = workflow.seat_info(conn, a["course_code"])
    taking_seat = values["status"] in site_data.SEAT_STATUSES and a["status"] not in site_data.SEAT_STATUSES
    workflow.set_status(a, values["status"], note=values["note"], remarks=values["remarks"])
    flash("Application updated.", "success")
    if taking_seat and filled + 1 > seats:
        flash(f"Seats for {a['course_code']} are now over capacity ({filled + 1} of {seats}).", "warn")
    return redirect(url_for("admin.application", admission_id=admission_id))


@admin_bp.route("/applications/<int:admission_id>/edit", methods=["GET", "POST"])
@security.login_required
def edit_application(admission_id):
    a = _get_application(admission_id)
    conn = get_db()
    courses = conn.execute("SELECT * FROM courses ORDER BY sort_order").fetchall()
    ctx = dict(a=a, courses=courses, states=site_data.STATES, genders=site_data.GENDERS,
               categories=site_data.CATEGORIES, qualifications=site_data.QUALIFICATIONS)
    if request.method == "POST":
        course = conn.execute("SELECT * FROM courses WHERE code = ?", ((request.form.get("course_code") or "").strip(),)).fetchone()
        form = request.form.copy()
        form["declaration"] = "yes"  # accepted when the applicant applied
        values, errors = validators.validate_application(form, course)
        if not errors and conn.execute(
                """SELECT 1 FROM admissions WHERE email = ? AND course_code = ? AND id != ?
                   AND status IN ('Pending', 'Under Review')""", (values["email"], course["code"], admission_id)).fetchone():
            errors["email"] = "Another open application exists for this email and programme."
        if errors:
            return render_template("admin/edit_application.html", values=values, errors=errors, **ctx), 422
        conn.execute(
            """UPDATE admissions SET full_name=?, father_name=?, mother_name=?, gender=?, dob=?, email=?, phone=?,
               category=?, nationality=?, qualification=?, percentage=?, course_code=?, course_name=?, address=?,
               city=?, state=?, pincode=?, updated_at=datetime('now') WHERE id=?""",
            (values["full_name"], values["father_name"], values["mother_name"], values["gender"], values["dob"],
             values["email"], values["phone"], values["category"] or None, values["nationality"],
             values["qualification"], values["percentage"], course["code"], course["name"], values["address"],
             values["city"], values["state"], values["pincode"], admission_id))
        audit("edit application", a["application_no"], commit=False)
        conn.commit()
        flash("Application details saved.", "success")
        return redirect(url_for("admin.application", admission_id=admission_id))
    return render_template("admin/edit_application.html", values=dict(a), errors={}, **ctx)


@admin_bp.post("/applications/<int:admission_id>/delete")
@admin_only
def delete_application(admission_id):
    a = _get_application(admission_id)
    conn = get_db()
    conn.execute("DELETE FROM admissions WHERE id = ?", (admission_id,))
    audit("delete application", a["application_no"], a["full_name"], commit=False)
    conn.commit()
    flash(f"Application {a['application_no']} deleted.", "success")
    return redirect(url_for("admin.applications"))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@admin_bp.get("/documents")
@security.login_required
def documents():
    show = request.args.get("show", "waiting")
    where = "WHERE d.status = 'Uploaded'" if show == "waiting" else ""
    rows = get_db().execute(
        f"""SELECT d.id, d.doc_type, d.filename, d.size, d.status, d.uploaded_at, a.id AS admission_id,
                   a.application_no, a.full_name FROM documents d JOIN admissions a ON a.id = d.admission_id
            {where} ORDER BY d.id DESC LIMIT 200""").fetchall()
    return render_template("admin/documents.html", rows=rows, show=show)


@admin_bp.get("/documents/<int:doc_id>")
@security.login_required
def download_document(doc_id):
    doc = get_db().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    return send_file(io.BytesIO(doc["data"]), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])


@admin_bp.post("/documents/<int:doc_id>/review")
@security.login_required
def review_document(doc_id):
    conn = get_db()
    doc = conn.execute("SELECT d.*, a.application_no FROM documents d JOIN admissions a ON a.id = d.admission_id WHERE d.id = ?",
                       (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    status = (request.form.get("status") or "").strip()
    note = " ".join((request.form.get("note") or "").split())[:200]
    if status not in site_data.DOC_STATUSES:
        abort(400)
    conn.execute("UPDATE documents SET status = ?, note = ? WHERE id = ?", (status, note or None, doc_id))
    audit("document " + status.lower(), doc["application_no"], doc["doc_type"], commit=False)
    conn.commit()
    flash(f"{doc['doc_type']} marked {status.lower()}.", "success")
    back = _safe_next(request.form.get("back")) or url_for("admin.application", admission_id=doc["admission_id"])
    return redirect(back)


# ---------------------------------------------------------------------------
# Merit lists and seats
# ---------------------------------------------------------------------------
def _merit_rows(conn, code):
    return conn.execute(
        """SELECT * FROM admissions WHERE course_code = ? AND status NOT IN ('Rejected', 'Cancelled')
           ORDER BY percentage DESC, created_at ASC, id ASC""", (code,)).fetchall()


@admin_bp.get("/merit")
@security.login_required
def merit():
    conn = get_db()
    courses = conn.execute("SELECT code, name FROM courses ORDER BY sort_order").fetchall()
    code = request.args.get("course") or (courses[0]["code"] if courses else "")
    if not any(c["code"] == code for c in courses):
        abort(404)
    seats, filled = workflow.seat_info(conn, code)
    rows = _merit_rows(conn, code)
    waiting = sum(1 for r in rows if r["status"] in ("Pending", "Under Review"))
    return render_template("admin/merit.html", courses=courses, code=code, rows=rows, seats=seats, filled=filled,
                           available=max(0, seats - filled), waiting=waiting)


@admin_bp.post("/merit/<code>/apply")
@admin_only
def merit_apply(code):
    conn = get_db()
    if conn.execute("SELECT 1 FROM courses WHERE code = ?", (code,)).fetchone() is None:
        abort(404)
    seats, filled = workflow.seat_info(conn, code)
    available = max(0, seats - filled)
    pending = [r for r in _merit_rows(conn, code) if r["status"] in ("Pending", "Under Review")]
    for i, row in enumerate(pending):
        if i < available:
            workflow.set_status(row, "Approved", note="Selected in the merit list.", quiet=True)
        else:
            workflow.set_status(row, "Waitlisted", note="All seats are filled. You are on the waiting list.", quiet=True)
    audit("merit list", code, f"{min(available, len(pending))} approved, {max(0, len(pending) - available)} waitlisted", commit=False)
    conn.commit()
    flash(f"{min(available, len(pending))} approved and {max(0, len(pending) - available)} waitlisted for {code}.", "success")
    return redirect(url_for("admin.merit", course=code))


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
@admin_bp.get("/messages")
@security.login_required
def messages():
    show = request.args.get("show", "all")
    where = "WHERE is_read = 0" if show == "unread" else ""
    rows = get_db().execute(f"SELECT * FROM contact_messages {where} ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("admin/messages.html", rows=rows, show=show, email_on=mailer.email_enabled())


@admin_bp.post("/messages/<int:message_id>/read")
@security.login_required
def message_read(message_id):
    state = 1 if request.form.get("state") == "1" else 0
    conn = get_db()
    conn.execute("UPDATE contact_messages SET is_read = ? WHERE id = ?", (state, message_id))
    conn.commit()
    show = request.form.get("show", "all")
    return redirect(url_for("admin.messages", show=show if show in ("all", "unread") else "all"))


@admin_bp.post("/messages/<int:message_id>/reply")
@security.login_required
def message_reply(message_id):
    conn = get_db()
    m = conn.execute("SELECT * FROM contact_messages WHERE id = ?", (message_id,)).fetchone()
    if m is None:
        abort(404)
    text = (request.form.get("reply") or "").strip()[:3000]
    if len(text) < 3:
        flash("Write a reply first.", "danger")
    elif not mailer.message_reply(m, text):
        flash("Email is not set up on this server, so the reply could not be sent. Use the mail link instead.", "danger")
    else:
        conn.execute("UPDATE contact_messages SET reply = ?, replied_at = datetime('now'), is_read = 1 WHERE id = ?",
                     (text, message_id))
        audit("reply message", m["email"], m["subject"], commit=False)
        conn.commit()
        flash("Reply sent.", "success")
    return redirect(url_for("admin.messages"))


@admin_bp.post("/messages/<int:message_id>/delete")
@admin_only
def message_delete(message_id):
    conn = get_db()
    conn.execute("DELETE FROM contact_messages WHERE id = ?", (message_id,))
    audit("delete message", message_id, commit=False)
    conn.commit()
    flash("Message deleted.", "success")
    return redirect(url_for("admin.messages"))


# ---------------------------------------------------------------------------
# Tickets (grievance and help desk)
# ---------------------------------------------------------------------------
@admin_bp.get("/tickets")
@security.login_required
def tickets():
    status = request.args.get("status", "active")
    where, params = "", []
    if status in site_data.TICKET_STATUSES:
        where, params = "WHERE status = ?", [status]
    elif status == "active":
        where = "WHERE status IN ('Open', 'In progress')"
    rows = get_db().execute(f"SELECT * FROM tickets {where} ORDER BY id DESC LIMIT 200", params).fetchall()
    return render_template("admin/tickets.html", rows=rows, status=status, statuses=site_data.TICKET_STATUSES)


@admin_bp.route("/tickets/<int:ticket_id>", methods=["GET", "POST"])
@security.login_required
def ticket(ticket_id):
    conn = get_db()
    t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if t is None:
        abort(404)
    if request.method == "POST":
        status = (request.form.get("status") or "").strip()
        response = (request.form.get("response") or "").strip()[:3000]
        if status not in site_data.TICKET_STATUSES:
            abort(400)
        conn.execute("UPDATE tickets SET status = ?, response = ?, updated_at = datetime('now') WHERE id = ?",
                     (status, response or None, ticket_id))
        audit("ticket", t["ticket_no"], status, commit=False)
        conn.commit()
        mailer.ticket_updated(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())
        flash("Ticket updated.", "success")
        return redirect(url_for("admin.ticket", ticket_id=ticket_id))
    return render_template("admin/ticket.html", t=t, statuses=site_data.TICKET_STATUSES)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
@admin_bp.get("/students")
@security.login_required
def students():
    q = (request.args.get("q") or "").strip()[:60]
    where, params = "", []
    if q:
        where, params = "WHERE (s.email LIKE ? ESCAPE '\\' OR s.full_name LIKE ? ESCAPE '\\')", [_like(q)] * 2
    rows = get_db().execute(
        f"""SELECT s.*, (SELECT COUNT(*) FROM admissions a WHERE a.student_id = s.id) AS apps
            FROM students s {where} ORDER BY s.id DESC LIMIT 200""", params).fetchall()
    return render_template("admin/students.html", rows=rows, q=q)


@admin_bp.get("/students/export.csv")
@admin_only
def students_export():
    rows = get_db().execute(
        """SELECT s.full_name, s.email, s.phone, s.created_at, s.last_login, s.is_active,
                  (SELECT COUNT(*) FROM admissions a WHERE a.student_id = s.id) AS apps FROM students s ORDER BY s.id""").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Email", "Phone", "Joined (UTC)", "Last login (UTC)", "Active", "Applications"])
    for r in rows:
        w.writerow([_cell(r["full_name"]), _cell(r["email"]), _cell(r["phone"]), r["created_at"], r["last_login"] or "",
                    "yes" if r["is_active"] else "no", r["apps"]])
    audit("export students", f"{len(rows)} rows")
    return Response(out.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=miutm-students.csv", "Cache-Control": "no-store"})


@admin_bp.post("/students/<int:student_id>/toggle")
@admin_only
def student_toggle(student_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if s is None:
        abort(404)
    new = 0 if s["is_active"] else 1
    conn.execute("UPDATE students SET is_active = ? WHERE id = ?", (new, student_id))
    audit("student " + ("enabled" if new else "disabled"), s["email"], commit=False)
    conn.commit()
    flash(f"Account for {s['email']} {'enabled' if new else 'disabled'}.", "success")
    return redirect(url_for("admin.students"))


@admin_bp.post("/students/<int:student_id>/reset")
@admin_only
def student_reset(student_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if s is None:
        abort(404)
    pw = request.form.get("password") or ""
    problem = validators.student_password_errors(pw)
    if problem:
        flash(f"Password not changed: {problem}", "danger")
    else:
        conn.execute("UPDATE students SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), student_id))
        audit("student password reset", s["email"], commit=False)
        conn.commit()
        flash(f"New password set for {s['email']}. Tell the student to change it after logging in.", "success")
    return redirect(url_for("admin.students"))


# ---------------------------------------------------------------------------
# My account
# ---------------------------------------------------------------------------
@admin_bp.route("/account", methods=["GET", "POST"])
@security.login_required
def account():
    staff = security.current_staff()
    conn = get_db()
    errors, pw_errors = {}, {}
    values = {"full_name": staff["full_name"], "email": staff["email"] or ""}
    if request.method == "POST":
        if request.form.get("action") == "password":
            if security.too_many("pw-change", str(staff["id"]), 6, 900):
                abort(429)
            ok = check_password_hash(staff["password_hash"], request.form.get("current") or "")
            pw_errors = validators.validate_new_password(ok, request.form.get("new") or "", request.form.get("confirm") or "")
            if not pw_errors:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(request.form["new"]), staff["id"]))
                audit("password changed", staff["username"], commit=False)
                conn.commit()
                flash("Password changed.", "success")
                return redirect(url_for("admin.account"))
        else:
            v, errors = validators.validate_staff(request.form, creating=False, existing_username=staff["username"])
            values = {"full_name": v["full_name"], "email": v["email"]}
            errors.pop("role", None)
            if not errors:
                conn.execute("UPDATE users SET full_name = ?, email = ? WHERE id = ?", (v["full_name"], v["email"] or None, staff["id"]))
                conn.commit()
                flash("Profile saved.", "success")
                return redirect(url_for("admin.account"))
    recent = conn.execute("SELECT * FROM audit_log WHERE actor = ? ORDER BY id DESC LIMIT 8", (staff["username"],)).fetchall()
    return render_template("admin/account.html", errors=errors, pw_errors=pw_errors, values=values, recent=recent)
