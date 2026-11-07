"""
admin.py - the staff area under /admin.

Two roles:
  admin     can do everything
  reviewer  can review applications, documents, payments and messages; cannot delete, run or publish merit lists,
            refund, manage content, settings or staff, or download backups.
Every page except sign-in needs a signed-in, active staff account, and every change is a POST with a CSRF token.
Important actions are written to the activity log.
"""
import csv
import io
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request, send_file, session,
                   url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
import notify
import payments
import pdfdocs
import security
import site_data
import validators
import workflow
from audit import audit
from db import get_db, like_pattern

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PAGE_SIZE = 20
_DUMMY_HASH = generate_password_hash("not-a-real-password")
admin_only = security.roles_required("admin")
L = lambda col: f"LOWER({col}) LIKE ? ESCAPE '\\'"


def _safe_next(target):
    if not target:
        return None
    parts = urlparse(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def ist_day_start_utc(day):
    """'2026-10-17' (an Indian calendar day) -> the UTC timestamp text where that day starts."""
    return (datetime.fromisoformat(day) - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def _valid_day(text):
    try:
        datetime.fromisoformat(text)
        return text
    except (ValueError, TypeError):
        return ""


@admin_bp.context_processor
def inject_admin_globals():
    staff = security.current_staff()
    if staff is None:
        return {}
    conn = get_db()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "staff": staff,
        "unread_count": one("SELECT COUNT(*) FROM contact_messages WHERE is_read = 0"),
        "open_tickets": one("SELECT COUNT(*) FROM tickets WHERE status IN ('Open','In progress')"),
        "docs_waiting": one("SELECT COUNT(*) FROM documents WHERE status = 'Pending'"),
        "staff_pending": one("SELECT COUNT(*) FROM users WHERE approved = 0"),
        "emails_failed": one("SELECT COUNT(*) FROM email_log WHERE status = 'Failed'"),
    }


# ---------------------------------------------------------------------------
# Sign in / out / register / password reset
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
    return render_template("admin/login.html", error=error, email_on=mailer.email_enabled())


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


def _staff_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="staff-reset")


@admin_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent = False
    if request.method == "POST" and mailer.email_enabled():
        if security.too_many("staff-forgot", security.client_ip(), 5, 3600):
            abort(429)
        name = (request.form.get("username") or "").strip().lower()[:60]
        user = get_db().execute("SELECT * FROM users WHERE lower(username) = ? AND is_active = 1 AND approved = 1 AND email IS NOT NULL",
                                (name,)).fetchone()
        if user:
            token = _staff_serializer().dumps({"id": user["id"], "h": user["password_hash"][-12:]})
            mailer.password_reset(user, url_for("admin.reset", token=token, _external=True))
        sent = True
    return render_template("admin/forgot.html", sent=sent, email_on=mailer.email_enabled())


@admin_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = _staff_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return render_template("admin/reset.html", bad=True, errors={}), 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (data["id"],)).fetchone()
    if user is None or user["password_hash"][-12:] != data["h"]:
        return render_template("admin/reset.html", bad=True, errors={}), 400
    errors = {}
    if request.method == "POST":
        pw, confirm = request.form.get("password") or "", request.form.get("confirm") or ""
        errors = validators.validate_new_password(True, pw, confirm)
        errors.pop("current", None)
        if not errors:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), user["id"]))
            audit("staff password reset (email)", user["username"], commit=False)
            conn.commit()
            security.sign_out_staff()
            flash("Password changed. Sign in with your new password.", "success")
            return redirect(url_for("admin.login"))
        return render_template("admin/reset.html", bad=False, errors=errors), 422
    return render_template("admin/reset.html", bad=False, errors=errors)


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
    one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]
    counts = {s: 0 for s in site_data.STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM admissions GROUP BY status"):
        counts[row["status"]] = row["n"]
    today = ist_day_start_utc(site_data.today_ist().isoformat())
    stats = {
        "total": sum(counts.values()),
        "today": one("SELECT COUNT(*) FROM admissions WHERE created_at >= ?", (today,)),
        "awaiting": counts["Submitted"] + counts["Under Review"] + counts["Documents Verification"] + counts["Merit Evaluation"],
        "approved": counts["Approved"] + counts["Admission Confirmed"],
        "rejected": counts["Rejected"],
        "paid": one("SELECT COUNT(*) FROM admissions WHERE payment_status = 'Paid'"),
        "unpaid": counts["Payment Pending"],
        "docs_pending": one("SELECT COUNT(*) FROM documents WHERE status = 'Pending'"),
        "revenue": one("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'Successful'"),
    }
    marks = ",".join("?" * len(site_data.SEAT_STATUSES))
    by_course = conn.execute(
        f"""SELECT c.name, c.code, c.seats, COUNT(a.id) AS applied,
                   SUM(CASE WHEN a.status IN ({marks}) THEN 1 ELSE 0 END) AS filled
            FROM courses c LEFT JOIN admissions a ON a.course_code = c.code
            GROUP BY c.id, c.name, c.code, c.seats, c.sort_order ORDER BY c.sort_order""", site_data.SEAT_STATUSES).fetchall()
    return render_template(
        "admin/dashboard.html", counts=counts, stats=stats, by_course=by_course, statuses_list=site_data.STATUSES,
        today_iso=site_data.today_ist().isoformat(),
        latest=conn.execute("SELECT * FROM admissions ORDER BY id DESC LIMIT 6").fetchall(),
        messages=conn.execute("SELECT * FROM contact_messages ORDER BY id DESC LIMIT 4").fetchall(),
        students=one("SELECT COUNT(*) FROM students"), drafts=one("SELECT COUNT(*) FROM drafts"),
        state=site_data.admissions_state(), engine="PostgreSQL" if current_app.config.get("DATABASE_URL") else "SQLite")


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def _filtered_query(args):
    where, params = [], []
    f = {"q": (args.get("q") or "").strip()[:60], "status": (args.get("status") or "").strip(),
         "course": (args.get("course") or "").strip(), "payment": (args.get("payment") or "").strip(),
         "docs": (args.get("docs") or "").strip(), "session": (args.get("session") or "").strip()[:12],
         "from": _valid_day((args.get("from") or "").strip()), "to": _valid_day((args.get("to") or "").strip())}
    if f["q"]:
        where.append("(" + " OR ".join(L(c) for c in ("application_no", "full_name", "phone", "email")) + ")")
        params += [like_pattern(f["q"])] * 4
    if f["status"] in site_data.STATUSES:
        where.append("status = ?"); params.append(f["status"])
    else:
        f["status"] = ""
    if f["course"]:
        where.append("course_code = ?"); params.append(f["course"])
    if f["payment"] in ("Paid", "Unpaid", "Refunded", "Waived"):
        where.append("payment_status = ?"); params.append(f["payment"])
    else:
        f["payment"] = ""
    docs = {"pending": "EXISTS (SELECT 1 FROM documents d WHERE d.admission_id = admissions.id AND d.status = 'Pending')",
            "rejected": "EXISTS (SELECT 1 FROM documents d WHERE d.admission_id = admissions.id AND d.status = 'Rejected')",
            "verified": "EXISTS (SELECT 1 FROM documents d WHERE d.admission_id = admissions.id) AND NOT EXISTS "
                        "(SELECT 1 FROM documents d WHERE d.admission_id = admissions.id AND d.status <> 'Verified')",
            "none": "NOT EXISTS (SELECT 1 FROM documents d WHERE d.admission_id = admissions.id)"}
    if f["docs"] in docs:
        where.append("(" + docs[f["docs"]] + ")")
    else:
        f["docs"] = ""
    if f["session"]:
        where.append("session = ?"); params.append(f["session"])
    if f["from"]:
        where.append("created_at >= ?"); params.append(ist_day_start_utc(f["from"]))
    if f["to"]:
        where.append("created_at < ?"); params.append(ist_day_start_utc((datetime.fromisoformat(f["to"]) + timedelta(days=1)).date().isoformat()))
    return (" WHERE " + " AND ".join(where)) if where else "", params, f


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
    flags = {}
    if rows:
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        for r in conn.execute(
                f"""SELECT admission_id, COUNT(*) AS n, SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) AS pending,
                           SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) AS rejected,
                           SUM(CASE WHEN status = 'Verified' THEN 1 ELSE 0 END) AS verified
                    FROM documents WHERE admission_id IN ({marks}) GROUP BY admission_id""", ids):
            flags[r["admission_id"]] = r
    courses = conn.execute("SELECT code, name FROM courses ORDER BY sort_order").fetchall()
    sessions = [r[0] for r in conn.execute("SELECT DISTINCT session FROM admissions WHERE session IS NOT NULL ORDER BY session")]
    return render_template("admin/applications.html", rows=rows, total=total, page=page, pages=pages, filters=filters,
                           courses=courses, statuses=site_data.STATUSES, flags=flags, sessions=sessions)


def _cell(value):
    """Stop spreadsheet programs from running text that starts with = + - @ as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


CSV_HEAD = ["Application no", "Submitted (UTC)", "Status", "Payment", "Session", "Name", "Father", "Mother", "Gender",
            "Date of birth", "Email", "Phone", "Category", "Nationality", "Qualification", "Percentage", "Merit rank",
            "Programme", "Address", "City", "State", "PIN"]


def _csv_rows(rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_HEAD)
    for r in rows:
        w.writerow([_cell(x) for x in (
            r["application_no"], r["created_at"], r["status"], r["payment_status"], r["session"], r["full_name"], r["father_name"],
            r["mother_name"], r["gender"], r["dob"], r["email"], r["phone"], r["category"], r["nationality"], r["qualification"],
            r["percentage"], r["merit_rank"], r["course_name"], r["address"], r["city"], r["state"], r["pincode"])])
    return out.getvalue()


def _csv_response(text, name):
    return Response(text, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}", "Cache-Control": "no-store"})


@admin_bp.get("/applications/export.csv")
@security.login_required
def export_csv():
    clause, params, _ = _filtered_query(request.args)
    rows = get_db().execute(f"SELECT * FROM admissions{clause} ORDER BY id DESC", params).fetchall()
    audit("export csv", f"{len(rows)} rows")
    return _csv_response(_csv_rows(rows), "miutm-applications.csv")


@admin_bp.post("/applications/bulk")
@security.login_required
def bulk():
    conn = get_db()
    ids = []
    for raw in request.form.getlist("ids")[:200]:
        if raw.isdigit():
            ids.append(int(raw))
    back = redirect(request.referrer if _safe_next(urlparse(request.referrer or "").path) else url_for("admin.applications"))
    if not ids:
        flash("Tick at least one application first.", "danger")
        return back
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM admissions WHERE id IN ({marks}) ORDER BY id", ids).fetchall()
    action = request.form.get("action")
    staff = security.current_staff()
    if action == "export":
        audit("bulk export", f"{len(rows)} applications")
        return _csv_response(_csv_rows(rows), "miutm-selected-applications.csv")
    if action == "status":
        status = request.form.get("status")
        note = " ".join((request.form.get("note") or "").split())[:400]
        if status not in site_data.STATUSES:
            flash("Choose the status to set.", "danger")
            return back
        if status == "Rejected" and not note:
            flash("Give a reason for rejecting applications. It is shown to the applicants.", "danger")
            return back
        changed = sum(1 for r in rows if workflow.set_status(r, status, note=note or None, quiet=True, reason=note or None))
        audit("bulk status", f"{changed} applications", status, commit=False)
        conn.commit()
        flash(f"{changed} application{'s' if changed != 1 else ''} moved to {status}.", "success")
        return back
    if action == "verify_docs":
        count = 0
        for r in rows:
            for d in conn.execute("SELECT id, doc_type FROM documents WHERE admission_id = ? AND status = 'Pending'", (r["id"],)).fetchall():
                conn.execute("UPDATE documents SET status = 'Verified', reviewed_by = ?, reviewed_at = datetime('now'), note = NULL WHERE id = ?",
                             (staff["username"], d["id"]))
                conn.execute("INSERT INTO document_events (admission_id, doc_type, action, actor) VALUES (?,?,?,?)",
                             (r["id"], d["doc_type"], "Verified", staff["username"]))
                count += 1
            notify.notify(r["student_id"], "Documents verified", "Your pending documents were verified.",
                          url_for("student.application", application_no=r["application_no"]), "document")
        audit("bulk verify documents", f"{count} documents in {len(rows)} applications", commit=False)
        conn.commit()
        flash(f"{count} document{'s' if count != 1 else ''} verified.", "success")
        return back
    flash("Choose an action.", "danger")
    return back


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
    seats, held = workflow.seat_info(conn, a["course_code"])
    docs = conn.execute("SELECT id, doc_type, filename, size, status, note, uploaded_at, reviewed_by, reviewed_at FROM documents "
                        "WHERE admission_id = ? ORDER BY id", (admission_id,)).fetchall()
    return render_template(
        "admin/application.html", a=a, statuses=site_data.STATUSES, seats=seats, filled=held, docs=docs,
        events=conn.execute("SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id DESC", (admission_id,)).fetchall(),
        doc_events=conn.execute("SELECT * FROM document_events WHERE admission_id = ? ORDER BY id DESC", (admission_id,)).fetchall(),
        pays=conn.execute("SELECT * FROM payments WHERE admission_id = ? ORDER BY id", (admission_id,)).fetchall(),
        required=site_data.required_docs(a["qualification"], a["category"]), doc_statuses=site_data.DOC_STATUSES,
        owner=conn.execute("SELECT full_name, email, email_verified FROM students WHERE id = ?", (a["student_id"],)).fetchone() if a["student_id"] else None)


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
    if a["status"] not in ("Approved", "Admission Confirmed"):
        flash("An admission letter is only available for Approved or Admission Confirmed applications.", "info")
        return redirect(url_for("admin.application", admission_id=admission_id))
    return render_template("print_page.html", a=a, partial="partials/_offer_letter.html",
                           back_url=url_for("admin.application", admission_id=admission_id), **workflow.offer_context(get_db(), a))


@admin_bp.post("/applications/<int:admission_id>/status")
@security.login_required
def update_status(admission_id):
    a = _get_application(admission_id)
    values, errors = validators.validate_status_update(request.form)
    if errors:
        flash(errors["status"], "danger")
        return redirect(url_for("admin.application", admission_id=admission_id))
    if values["status"] == "Rejected" and a["status"] != "Rejected" and not values["note"]:
        flash("Give a reason for rejecting this application in the message box. The applicant sees it.", "danger")
        return redirect(url_for("admin.application", admission_id=admission_id))
    conn = get_db()
    seats, held = workflow.seat_info(conn, a["course_code"])
    taking_seat = values["status"] in site_data.SEAT_STATUSES and a["status"] not in site_data.SEAT_STATUSES
    workflow.set_status(a, values["status"], note=values["note"], remarks=values["remarks"], reason=values["note"])
    flash("Application updated.", "success")
    if taking_seat and held + 1 > seats:
        flash(f"Seats for {a['course_code']} are now over capacity ({held + 1} of {seats}).", "warn")
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
        if not errors and a["student_id"] and course["code"] != a["course_code"] and conn.execute(
                "SELECT 1 FROM admissions WHERE student_id = ? AND course_code = ? AND session = ? AND id != ? "
                "AND status NOT IN ('Cancelled', 'Rejected')", (a["student_id"], course["code"], a["session"], admission_id)).fetchone():
            errors["course_code"] = "This student already has an open application for that programme in this session."
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
    if conn.execute("SELECT 1 FROM payments WHERE admission_id = ?", (admission_id,)).fetchone():
        flash("This application has payment records, which must be kept. Cancel or reject it instead.", "danger")
        return redirect(url_for("admin.application", admission_id=admission_id))
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
    where = "WHERE d.status = 'Pending'" if show == "waiting" else ("WHERE d.status = 'Rejected'" if show == "rejected" else "")
    rows = get_db().execute(
        f"""SELECT d.id, d.doc_type, d.filename, d.size, d.status, d.note, d.uploaded_at, a.id AS admission_id,
                   a.application_no, a.full_name FROM documents d JOIN admissions a ON a.id = d.admission_id
            {where} ORDER BY d.id DESC LIMIT 200""").fetchall()
    return render_template("admin/documents.html", rows=rows, show=show)


@admin_bp.get("/documents/<int:doc_id>")
@security.login_required
def download_document(doc_id):
    doc = get_db().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    return send_file(io.BytesIO(bytes(doc["data"])), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])


@admin_bp.post("/documents/<int:doc_id>/review")
@security.login_required
def review_document(doc_id):
    conn = get_db()
    doc = conn.execute("SELECT d.*, a.application_no, a.student_id FROM documents d JOIN admissions a ON a.id = d.admission_id WHERE d.id = ?",
                       (doc_id,)).fetchone()
    if doc is None:
        abort(404)
    status = (request.form.get("status") or "").strip()
    note = " ".join((request.form.get("note") or "").split())[:200]
    back = _safe_next(request.form.get("back")) or url_for("admin.application", admission_id=doc["admission_id"])
    if status not in site_data.DOC_STATUSES:
        abort(400)
    if status == "Rejected" and not note:
        flash("Give a reason for rejecting the document, such as 'The copy is unclear. Please upload a clearer one.'", "danger")
        return redirect(back)
    staff = security.current_staff()
    conn.execute("UPDATE documents SET status = ?, note = ?, reviewed_by = ?, reviewed_at = datetime('now') WHERE id = ?",
                 (status, note or None, staff["username"], doc_id))
    conn.execute("INSERT INTO document_events (admission_id, doc_type, action, note, actor) VALUES (?,?,?,?,?)",
                 (doc["admission_id"], doc["doc_type"], status, note or None, staff["username"]))
    link = url_for("student.application", application_no=doc["application_no"]) + "#documents"
    if status == "Verified":
        notify.notify(doc["student_id"], f"{doc['doc_type']} verified", "The office has verified this document.", link, "document")
    elif status == "Rejected":
        notify.notify(doc["student_id"], f"{doc['doc_type']} needs attention", note, link, "document")
    audit("document " + status.lower(), doc["application_no"], doc["doc_type"], commit=False)
    conn.commit()
    flash(f"{doc['doc_type']} marked {status.lower()}.", "success")
    return redirect(back)


# ---------------------------------------------------------------------------
# Merit lists and seats
# ---------------------------------------------------------------------------
@admin_bp.get("/merit")
@security.login_required
def merit():
    conn = get_db()
    courses = conn.execute("SELECT code, name FROM courses ORDER BY sort_order").fetchall()
    code = request.args.get("course") or (courses[0]["code"] if courses else "")
    if not any(c["code"] == code for c in courses):
        abort(404)
    seats, held = workflow.seat_info(conn, code)
    rows = conn.execute("SELECT * FROM admissions WHERE course_code = ? AND status NOT IN ('Rejected', 'Cancelled', 'Payment Pending') "
                        "ORDER BY CASE WHEN merit_rank IS NULL THEN 1 ELSE 0 END, merit_rank, percentage DESC, created_at, id", (code,)).fetchall()
    session_label = site_data.current_cycle()["session"]
    pub = conn.execute("SELECT * FROM merit_publications WHERE course_code = ? AND session = ?", (code, session_label)).fetchone()
    waiting = sum(1 for r in rows if r["status"] in site_data.REVIEW_POOL)
    return render_template("admin/merit.html", courses=courses, code=code, rows=rows, seats=seats, filled=held,
                           available=max(0, seats - held), waiting=waiting, pub=pub, session_label=session_label)


@admin_bp.post("/merit/<code>/apply")
@admin_only
def merit_apply(code):
    conn = get_db()
    if conn.execute("SELECT 1 FROM courses WHERE code = ?", (code,)).fetchone() is None:
        abort(404)
    selected, waitlisted = workflow.run_merit(conn, code)
    audit("merit list", code, f"{selected} selected, {waitlisted} waitlisted", commit=False)
    conn.commit()
    flash(f"Ranks saved. {selected} selected and {waitlisted} waitlisted for {code}.", "success")
    return redirect(url_for("admin.merit", course=code))


@admin_bp.post("/merit/<code>/publish")
@admin_only
def merit_publish(code):
    conn = get_db()
    if conn.execute("SELECT 1 FROM courses WHERE code = ?", (code,)).fetchone() is None:
        abort(404)
    label = site_data.current_cycle()["session"]
    if request.form.get("unpublish") == "1":
        conn.execute("DELETE FROM merit_publications WHERE course_code = ? AND session = ?", (code, label))
        flash("Merit list unpublished.", "success")
    else:
        if conn.execute("SELECT COUNT(*) FROM admissions WHERE course_code = ? AND merit_rank IS NOT NULL", (code,)).fetchone()[0] == 0:
            flash("Run the merit list first so there are ranks to publish.", "danger")
            return redirect(url_for("admin.merit", course=code))
        conn.execute("DELETE FROM merit_publications WHERE course_code = ? AND session = ?", (code, label))
        conn.execute("INSERT INTO merit_publications (course_code, session, published_by) VALUES (?,?,?)",
                     (code, label, security.current_staff()["username"]))
        for r in conn.execute("SELECT student_id, application_no FROM admissions WHERE course_code = ? AND merit_rank IS NOT NULL "
                              "AND student_id IS NOT NULL", (code,)).fetchall():
            notify.notify(r["student_id"], f"Merit list published: {code}", "The merit list for your programme is out. See your status.",
                          url_for("student.application", application_no=r["application_no"]), "merit")
        flash("Merit list published. Students were notified.", "success")
    audit("merit publish", code, commit=False)
    conn.commit()
    return redirect(url_for("admin.merit", course=code))


@admin_bp.get("/merit/<code>/export.csv")
@security.login_required
def merit_export(code):
    rows = get_db().execute("SELECT * FROM admissions WHERE course_code = ? AND merit_rank IS NOT NULL ORDER BY merit_rank", (code,)).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Application no", "Name", "Percentage", "Category", "Status"])
    for r in rows:
        w.writerow([r["merit_rank"], r["application_no"], _cell(r["full_name"]), r["percentage"], r["category"] or "", r["status"]])
    audit("export merit list", code)
    return _csv_response(out.getvalue(), f"merit-list-{code}.csv")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def _payment_query(args):
    where, params = [], []
    f = {"q": (args.get("q") or "").strip()[:60], "status": (args.get("status") or "").strip(),
         "purpose": (args.get("purpose") or "").strip(), "course": (args.get("course") or "").strip(),
         "from": _valid_day((args.get("from") or "").strip()), "to": _valid_day((args.get("to") or "").strip())}
    if f["q"]:
        where.append("(" + " OR ".join(L(c) for c in ("p.order_id", "p.transaction_id", "a.application_no", "a.full_name")) + ")")
        params += [like_pattern(f["q"])] * 4
    if f["status"] in site_data.PAYMENT_STATUSES:
        where.append("p.status = ?"); params.append(f["status"])
    else:
        f["status"] = ""
    if f["purpose"] in site_data.PAYMENT_PURPOSES:
        where.append("p.purpose = ?"); params.append(f["purpose"])
    else:
        f["purpose"] = ""
    if f["course"]:
        where.append("a.course_code = ?"); params.append(f["course"])
    if f["from"]:
        where.append("p.created_at >= ?"); params.append(ist_day_start_utc(f["from"]))
    if f["to"]:
        where.append("p.created_at < ?"); params.append(ist_day_start_utc((datetime.fromisoformat(f["to"]) + timedelta(days=1)).date().isoformat()))
    return (" WHERE " + " AND ".join(where)) if where else "", params, f


_PAY_SELECT = ("SELECT p.*, a.application_no, a.full_name, a.course_code FROM payments p "
               "JOIN admissions a ON a.id = p.admission_id")


@admin_bp.get("/payments")
@security.login_required
def payments_list():
    conn = get_db()
    clause, params, filters = _payment_query(request.args)
    total = conn.execute(f"SELECT COUNT(*) FROM payments p JOIN admissions a ON a.id = p.admission_id{clause}", params).fetchone()[0]
    pages = max(1, -(-total // PAGE_SIZE))
    try:
        page = min(max(1, int(request.args.get("page", 1))), pages)
    except ValueError:
        page = 1
    rows = conn.execute(f"{_PAY_SELECT}{clause} ORDER BY p.id DESC LIMIT ? OFFSET ?", params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    summary = conn.execute(f"SELECT COALESCE(SUM(CASE WHEN p.status = 'Successful' THEN p.amount ELSE 0 END), 0) AS received, "
                           f"COALESCE(SUM(CASE WHEN p.status = 'Refunded' THEN p.amount ELSE 0 END), 0) AS refunded "
                           f"FROM payments p JOIN admissions a ON a.id = p.admission_id{clause}", params).fetchone()
    return render_template("admin/payments.html", rows=rows, total=total, page=page, pages=pages, filters=filters, summary=summary,
                           statuses=site_data.PAYMENT_STATUSES, purposes=site_data.PAYMENT_PURPOSES,
                           courses=conn.execute("SELECT code, name FROM courses ORDER BY sort_order").fetchall())


@admin_bp.get("/payments/export.csv")
@security.login_required
def payments_export():
    clause, params, _ = _payment_query(request.args)
    rows = get_db().execute(f"{_PAY_SELECT}{clause} ORDER BY p.id DESC", params).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Order ID", "Application no", "Student", "Programme", "Purpose", "Amount", "Method", "Status", "Transaction ID",
                "Payment ID", "Created (UTC)", "Paid (UTC)", "Refunded (UTC)"])
    for r in rows:
        w.writerow([r["order_id"], r["application_no"], _cell(r["full_name"]), r["course_code"], r["purpose"], r["amount"], r["method"] or "",
                    r["status"], r["transaction_id"] or "", r["payment_ref"] or "", r["created_at"], r["paid_at"] or "", r["refunded_at"] or ""])
    audit("export payments", f"{len(rows)} rows")
    return _csv_response(out.getvalue(), "miutm-payments.csv")


@admin_bp.get("/payments/<int:payment_id>")
@security.login_required
def payment_detail(payment_id):
    conn = get_db()
    p = conn.execute(f"{_PAY_SELECT} WHERE p.id = ?", (payment_id,)).fetchone()
    if p is None:
        abort(404)
    return render_template("admin/payment.html", p=p, events=conn.execute(
        "SELECT * FROM payment_events WHERE payment_id = ? ORDER BY id DESC", (payment_id,)).fetchall())


@admin_bp.get("/payments/<int:payment_id>/receipt.pdf")
@security.login_required
def payment_receipt(payment_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if p is None or p["status"] not in ("Successful", "Refunded"):
        abort(404)
    a = conn.execute("SELECT * FROM admissions WHERE id = ?", (p["admission_id"],)).fetchone()
    data = pdfdocs.payment_receipt_pdf(site_data.current_site(), a, p, site_data.DEMO_MODE)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=receipt-{p['order_id']}.pdf"})


@admin_bp.post("/payments/<int:payment_id>/refund")
@admin_only
def payment_refund(payment_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if p is None:
        abort(404)
    reason = " ".join((request.form.get("reason") or "").split())[:300]
    if len(reason) < 5:
        flash("Give a reason for the refund (at least a few words).", "danger")
    elif payments.refund(conn, p, reason):
        flash("Payment marked as refunded. Remember to return the money through the payment provider.", "success")
    else:
        flash("Only a successful payment can be refunded.", "danger")
    return redirect(url_for("admin.payment_detail", payment_id=payment_id))


# ---------------------------------------------------------------------------
# Email log
# ---------------------------------------------------------------------------
@admin_bp.get("/emails")
@admin_only
def emails():
    show = request.args.get("show", "all")
    where = "WHERE status IN ('Failed', 'Retrying')" if show == "failed" else ""
    rows = get_db().execute(f"SELECT id, to_email, subject, status, attempts, last_error, created_at, sent_at FROM email_log {where} "
                            "ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("admin/emails.html", rows=rows, show=show, email_on=mailer.email_enabled())


@admin_bp.post("/emails/retry")
@admin_only
def emails_retry():
    sent, failed = mailer.retry_failed(current_app._get_current_object())
    audit("retry emails", f"{sent} sent, {failed} failed")
    flash(f"Retried failed emails: {sent} sent, {failed} still failing.", "success" if not failed else "warn")
    return redirect(url_for("admin.emails", show="failed"))


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
        conn.execute("UPDATE contact_messages SET reply = ?, replied_at = datetime('now'), is_read = 1 WHERE id = ?", (text, message_id))
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
# Tickets
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
        conn.execute("UPDATE tickets SET status = ?, response = ?, updated_at = datetime('now') WHERE id = ?", (status, response or None, ticket_id))
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
        where, params = f"WHERE ({L('s.email')} OR {L('s.full_name')})", [like_pattern(q)] * 2
    rows = get_db().execute(
        f"""SELECT s.*, (SELECT COUNT(*) FROM admissions a WHERE a.student_id = s.id) AS apps
            FROM students s {where} ORDER BY s.id DESC LIMIT 200""", params).fetchall()
    return render_template("admin/students.html", rows=rows, q=q)


@admin_bp.get("/students/export.csv")
@admin_only
def students_export():
    rows = get_db().execute(
        """SELECT s.full_name, s.email, s.phone, s.created_at, s.last_login, s.is_active, s.email_verified,
                  (SELECT COUNT(*) FROM admissions a WHERE a.student_id = s.id) AS apps FROM students s ORDER BY s.id""").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Email", "Phone", "Joined (UTC)", "Last login (UTC)", "Active", "Email verified", "Applications"])
    for r in rows:
        w.writerow([_cell(r["full_name"]), _cell(r["email"]), _cell(r["phone"]), r["created_at"], r["last_login"] or "",
                    "yes" if r["is_active"] else "no", "yes" if r["email_verified"] else "no", r["apps"]])
    audit("export students", f"{len(rows)} rows")
    return _csv_response(out.getvalue(), "miutm-students.csv")


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


@admin_bp.post("/students/<int:student_id>/verify")
@admin_only
def student_verify(student_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if s is None:
        abort(404)
    conn.execute("UPDATE students SET email_verified = 1 WHERE id = ?", (student_id,))
    audit("student verified by staff", s["email"], commit=False)
    conn.commit()
    flash(f"{s['email']} marked as verified.", "success")
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
