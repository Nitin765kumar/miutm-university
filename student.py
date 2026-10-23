"""
student.py - student accounts and dashboard under /student.

A student signs up with email and password, then sees every application linked to the account:
status timeline, document uploads, edit while Pending, withdraw, printable form and offer letter.
Applications made without an account can be linked by proving the application number and date
of birth (see /student/claim).
"""
import io
import sqlite3
from urllib.parse import urlparse

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, send_file, session,
                   url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
import security
import site_data
import validators
import workflow
from audit import audit
from db import get_db

student_bp = Blueprint("student", __name__, url_prefix="/student")
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _safe_next(target):
    if not target:
        return None
    parts = urlparse(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def _link_application(student_id, application_no):
    """Attach an application to a student, only if it has no owner yet."""
    conn = get_db()
    conn.execute("UPDATE admissions SET student_id = ? WHERE application_no = ? AND student_id IS NULL",
                 (student_id, application_no))
    conn.commit()


def _sign_in(student, remember=True):
    """Sign the student in without touching a staff sign-in held by the same browser."""
    nxt = _safe_next(session.pop("next", None))
    security.sign_in_student(student, remember)
    conn = get_db()
    conn.execute("UPDATE students SET last_login = datetime('now') WHERE id = ?", (student["id"],))
    conn.commit()
    last = session.get("last_app")
    if last:  # an application made before the account existed in this browser
        _link_application(student["id"], last["no"])
    return nxt


def _own(application_no):
    row = get_db().execute(
        """SELECT a.*, c.slug AS course_slug, c.level AS course_level
           FROM admissions a LEFT JOIN courses c ON c.code = a.course_code
           WHERE a.application_no = ? AND a.student_id = ?""",
        (application_no.upper(), security.current_student()["id"])).fetchone()
    if row is None:
        abort(404)
    return row


# ---------------------------------------------------------------------------
# Sign up, log in, log out
# ---------------------------------------------------------------------------
@student_bp.route("/register", methods=["GET", "POST"])
def register():
    if security.current_student():
        return redirect(url_for("student.dashboard"))
    values, errors = {}, {}
    last = session.get("last_app")
    if request.method == "GET" and last:
        values = {"full_name": last["name"], "email": last["email"]}
    if request.method == "POST":
        if security.too_many("register", security.client_ip(), 6, 3600):
            abort(429)
        if request.form.get("website"):
            return redirect(url_for("index"))
        values, errors = validators.validate_student_register(request.form)
        conn = get_db()
        if not errors and conn.execute("SELECT 1 FROM students WHERE email = ?", (values["email"],)).fetchone():
            errors["email"] = "An account with this email already exists. Log in instead."
        if not errors:
            cur = conn.execute(
                "INSERT INTO students (email, password_hash, full_name, phone) VALUES (?,?,?,?)",
                (values["email"], generate_password_hash(request.form["password"]), values["full_name"],
                 values["phone"] or None))
            conn.commit()
            student = conn.execute("SELECT * FROM students WHERE id = ?", (cur.lastrowid,)).fetchone()
            nxt = _sign_in(student, remember=True)
            audit("student register", student["email"])
            flash("Your account is ready. Welcome!", "success")
            return redirect(nxt or url_for("student.dashboard"))
        return render_template("student/register.html", values=values, errors=errors), 422
    return render_template("student/register.html", values=values, errors=errors)


@student_bp.route("/login", methods=["GET", "POST"])
def login():
    if security.current_student():
        return redirect(url_for("student.dashboard"))
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()[:120]
        if (security.too_many("slogin-ip", security.client_ip(), 12, 900)
                or security.too_many("slogin-user", email, 6, 900)):
            abort(429)
        student = get_db().execute("SELECT * FROM students WHERE email = ? AND is_active = 1", (email,)).fetchone()
        ok = check_password_hash(student["password_hash"] if student else _DUMMY_HASH,
                                 request.form.get("password") or "")
        if student and ok:
            nxt = _sign_in(student, remember=request.form.get("remember") == "1")
            return redirect(nxt or url_for("student.dashboard"))
        error = "Wrong email or password."
    return render_template("student/login.html", error=error, email_on=mailer.email_enabled())


@student_bp.post("/logout")
def logout():
    security.sign_out_student()
    flash("You have logged out.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Forgot / reset password (only works when email is switched on)
# ---------------------------------------------------------------------------
def _serializer():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.secret_key, salt="student-reset")


@student_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent = False
    if request.method == "POST" and mailer.email_enabled():
        if security.too_many("forgot", security.client_ip(), 5, 3600):
            abort(429)
        email = (request.form.get("email") or "").strip().lower()[:120]
        student = get_db().execute("SELECT * FROM students WHERE email = ? AND is_active = 1", (email,)).fetchone()
        if student:
            token = _serializer().dumps({"id": student["id"], "h": student["password_hash"][-12:]})
            mailer.password_reset(student, url_for("student.reset", token=token, _external=True))
        sent = True  # same answer whether or not the email has an account
    return render_template("student/forgot.html", sent=sent, email_on=mailer.email_enabled())


@student_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return render_template("student/reset.html", bad=True, errors={}), 400
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ? AND is_active = 1", (data["id"],)).fetchone()
    if student is None or student["password_hash"][-12:] != data["h"]:  # already used
        return render_template("student/reset.html", bad=True, errors={}), 400
    errors = {}
    if request.method == "POST":
        pw, confirm = request.form.get("password") or "", request.form.get("confirm") or ""
        problem = validators.student_password_errors(pw)
        if problem:
            errors["password"] = problem
        elif pw != confirm:
            errors["confirm"] = "The two passwords do not match."
        else:
            conn.execute("UPDATE students SET password_hash = ? WHERE id = ?",
                         (generate_password_hash(pw), student["id"]))
            conn.commit()
            security.sign_out_student()
            flash("Password changed. Log in with your new password.", "success")
            return redirect(url_for("student.login"))
        return render_template("student/reset.html", bad=False, errors=errors), 422
    return render_template("student/reset.html", bad=False, errors=errors)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@student_bp.get("/dashboard")
@security.student_required
def dashboard():
    conn = get_db()
    me = security.current_student()
    apps = conn.execute(
        """SELECT a.*, c.slug AS course_slug FROM admissions a
           LEFT JOIN courses c ON c.code = a.course_code
           WHERE a.student_id = ? ORDER BY a.id DESC""", (me["id"],)).fetchall()
    progress = {}
    for a in apps:
        have = conn.execute("SELECT doc_type, status FROM documents WHERE admission_id = ?", (a["id"],)).fetchall()
        need = site_data.required_docs(a["qualification"], a["category"])
        got = {d["doc_type"] for d in have}
        verified = {d["doc_type"] for d in have if d["status"] == "Verified"}
        progress[a["id"]] = {"need": len(need), "uploaded": len([n for n in need if n in got]),
                             "verified": len([n for n in need if n in verified])}
    notices = conn.execute("SELECT * FROM notices WHERE is_published = 1 ORDER BY published_on DESC, id DESC LIMIT 3").fetchall()
    draft = None
    row = conn.execute("SELECT data, updated_at FROM drafts WHERE student_id = ?", (me["id"],)).fetchone()
    if row:
        import json
        try:
            data = json.loads(row["data"])
        except ValueError:
            data = {}
        course = conn.execute("SELECT name FROM courses WHERE code = ?", (data.get("course_code", ""),)).fetchone()
        draft = {"course": course["name"] if course else None, "updated": row["updated_at"],
                 "files": conn.execute("SELECT COUNT(*) FROM draft_documents WHERE student_id = ?", (me["id"],)).fetchone()[0]}
    return render_template("student/dashboard.html", me=me, apps=apps, progress=progress, notices=notices, draft=draft,
                           status_next=site_data.STATUS_NEXT, withdrawable=site_data.WITHDRAWABLE)


@student_bp.get("/applications/<application_no>")
@security.student_required
def application(application_no):
    a = _own(application_no)
    conn = get_db()
    events = conn.execute("SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id DESC", (a["id"],)).fetchall()
    docs = {d["doc_type"]: d for d in conn.execute(
        "SELECT id, doc_type, filename, size, status, note, uploaded_at FROM documents WHERE admission_id = ?",
        (a["id"],)).fetchall()}
    required = site_data.required_docs(a["qualification"], a["category"])
    optional = [d for d in site_data.DOC_TYPES if d not in required]
    seats, filled = workflow.seat_info(conn, a["course_code"])
    return render_template("student/application.html", a=a, events=events, docs=docs, required=required,
                           optional=optional, status_help=site_data.STATUS_HELP, status_next=site_data.STATUS_NEXT,
                           can_edit=a["status"] == "Pending", can_withdraw=a["status"] in site_data.WITHDRAWABLE,
                           can_upload=a["status"] not in ("Rejected", "Cancelled"),
                           has_offer=a["status"] in ("Approved", "Enrolled"))


@student_bp.route("/applications/<application_no>/edit", methods=["GET", "POST"])
@security.student_required
def edit_application(application_no):
    a = _own(application_no)
    if a["status"] != "Pending":
        flash("Only applications that are still Pending can be edited. Contact the admissions office for changes.", "danger")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    conn = get_db()
    courses = conn.execute("SELECT * FROM courses WHERE is_published = 1 ORDER BY sort_order").fetchall()
    ctx = dict(a=a, courses=courses, states=site_data.STATES, genders=site_data.GENDERS,
               categories=site_data.CATEGORIES, qualifications=site_data.QUALIFICATIONS)
    if request.method == "POST":
        course = conn.execute("SELECT * FROM courses WHERE code = ? AND is_published = 1",
                              ((request.form.get("course_code") or "").strip(),)).fetchone()
        form = request.form.copy()
        form["declaration"] = "yes"
        values, errors = validators.validate_application(form, course)
        if not errors and conn.execute(
                """SELECT 1 FROM admissions WHERE email = ? AND course_code = ? AND id != ?
                   AND status IN ('Pending', 'Under Review')""", (values["email"], course["code"], a["id"])).fetchone():
            errors["email"] = "You already have an open application for this programme with this email."
        if errors:
            return render_template("student/edit.html", values=values, errors=errors, **ctx), 422
        conn.execute(
            """UPDATE admissions SET full_name=?, father_name=?, mother_name=?, gender=?, dob=?, email=?, phone=?,
               category=?, nationality=?, qualification=?, percentage=?, course_code=?, course_name=?, address=?,
               city=?, state=?, pincode=?, updated_at=datetime('now') WHERE id=?""",
            (values["full_name"], values["father_name"], values["mother_name"], values["gender"], values["dob"],
             values["email"], values["phone"], values["category"] or None, values["nationality"],
             values["qualification"], values["percentage"], course["code"], course["name"], values["address"],
             values["city"], values["state"], values["pincode"], a["id"]))
        conn.execute("INSERT INTO admission_events (admission_id, status, note) VALUES (?,?,?)",
                     (a["id"], "Pending", "Details updated by the applicant."))
        audit("student edit", a["application_no"], commit=False)
        conn.commit()
        flash("Your application was updated.", "success")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    return render_template("student/edit.html", values=dict(a), errors={}, **ctx)


@student_bp.post("/applications/<application_no>/withdraw")
@security.student_required
def withdraw(application_no):
    a = _own(application_no)
    if a["status"] not in site_data.WITHDRAWABLE:
        flash("This application can no longer be withdrawn.", "danger")
    else:
        workflow.set_status(a, "Cancelled", note="Withdrawn by the applicant.")
        flash("Your application was withdrawn.", "success")
    return redirect(url_for("student.application", application_no=a["application_no"]))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@student_bp.post("/applications/<application_no>/documents")
@security.student_required
def upload_document(application_no):
    a = _own(application_no)
    back = redirect(url_for("student.application", application_no=a["application_no"]) + "#documents")
    if a["status"] in ("Rejected", "Cancelled"):
        flash("Documents cannot be added to a closed application.", "danger")
        return back
    if security.too_many("upload", str(security.current_student()["id"]), 30, 3600):
        abort(429)
    doc_type = (request.form.get("doc_type") or "").strip()
    data, mime, name, error = validators.check_upload(request.files.get("file"), doc_type)
    if error:
        flash(error, "danger")
        return back
    conn = get_db()
    old = conn.execute("SELECT id, status FROM documents WHERE admission_id = ? AND doc_type = ?",
                       (a["id"], doc_type)).fetchone()
    if old and old["status"] == "Verified":
        flash(f"Your {doc_type.lower()} is already verified, so it cannot be replaced.", "danger")
        return back
    if old:
        conn.execute("DELETE FROM documents WHERE id = ?", (old["id"],))
    conn.execute("INSERT INTO documents (admission_id, doc_type, filename, mime, size, data) VALUES (?,?,?,?,?,?)",
                 (a["id"], doc_type, name, mime, len(data), data))
    audit("document upload", a["application_no"], doc_type, commit=False)
    conn.commit()
    flash(f"{doc_type} uploaded. The office will verify it.", "success")
    return back


@student_bp.post("/applications/<application_no>/documents/<int:doc_id>/delete")
@security.student_required
def delete_document(application_no, doc_id):
    a = _own(application_no)
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ? AND admission_id = ?", (doc_id, a["id"])).fetchone()
    if doc is None:
        abort(404)
    if doc["status"] == "Verified":
        flash("A verified document cannot be removed.", "danger")
    else:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        flash("Document removed.", "success")
    return redirect(url_for("student.application", application_no=a["application_no"]) + "#documents")


@student_bp.get("/documents/<int:doc_id>")
@security.student_required
def download_document(doc_id):
    doc = get_db().execute(
        """SELECT d.* FROM documents d JOIN admissions a ON a.id = d.admission_id
           WHERE d.id = ? AND a.student_id = ?""", (doc_id, security.current_student()["id"])).fetchone()
    if doc is None:
        abort(404)
    return send_file(io.BytesIO(doc["data"]), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])


# ---------------------------------------------------------------------------
# Printable pages
# ---------------------------------------------------------------------------
@student_bp.get("/applications/<application_no>/print")
@security.student_required
def print_form(application_no):
    a = _own(application_no)
    return render_template("print_page.html", a=a, partial="partials/_application_sheet.html",
                           back_url=url_for("student.application", application_no=a["application_no"]))


@student_bp.get("/applications/<application_no>/offer")
@security.student_required
def offer_letter(application_no):
    a = _own(application_no)
    if a["status"] not in ("Approved", "Enrolled"):
        flash("Your offer letter is available once the application is approved.", "info")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    return render_template("print_page.html", a=a, partial="partials/_offer_letter.html",
                           back_url=url_for("student.application", application_no=a["application_no"]),
                           **workflow.offer_context(get_db(), a))


# ---------------------------------------------------------------------------
# Claim an application made without an account
# ---------------------------------------------------------------------------
@student_bp.route("/claim", methods=["GET", "POST"])
@security.student_required
def claim():
    error = None
    if request.method == "POST":
        if security.too_many("claim", security.client_ip(), 10, 600):
            abort(429)
        number = (request.form.get("application_no") or "").strip().upper()
        dob = (request.form.get("dob") or "").strip()
        conn = get_db()
        row = conn.execute("SELECT * FROM admissions WHERE application_no = ? AND dob = ?", (number, dob)).fetchone()
        if row is None:
            error = "We could not find an application with that number and date of birth."
        elif row["student_id"] and row["student_id"] != security.current_student()["id"]:
            error = "That application is already linked to another account. Contact the admissions office."
        else:
            _link_application(security.current_student()["id"], number)
            audit("student claim", number)
            flash(f"Application {number} was added to your account.", "success")
            return redirect(url_for("student.application", application_no=number))
    return render_template("student/claim.html", error=error)


# ---------------------------------------------------------------------------
# Profile and password
# ---------------------------------------------------------------------------
@student_bp.route("/profile", methods=["GET", "POST"])
@security.student_required
def profile():
    me = security.current_student()
    values, errors = {"full_name": me["full_name"], "phone": me["phone"] or ""}, {}
    if request.method == "POST":
        values, errors = validators.validate_profile(request.form)
        if not errors:
            conn = get_db()
            conn.execute("UPDATE students SET full_name = ?, phone = ? WHERE id = ?",
                         (values["full_name"], values["phone"] or None, me["id"]))
            conn.commit()
            flash("Profile saved.", "success")
            return redirect(url_for("student.profile"))
        return render_template("student/profile.html", me=me, values=values, errors=errors), 422
    return render_template("student/profile.html", me=me, values=values, errors=errors)


@student_bp.route("/password", methods=["GET", "POST"])
@security.student_required
def password():
    errors = {}
    if request.method == "POST":
        me = security.current_student()
        if security.too_many("spw", str(me["id"]), 6, 900):
            abort(429)
        ok = check_password_hash(me["password_hash"], request.form.get("current") or "")
        errors = validators.validate_student_password_change(ok, request.form.get("new") or "",
                                                            request.form.get("confirm") or "")
        if not errors:
            conn = get_db()
            conn.execute("UPDATE students SET password_hash = ? WHERE id = ?",
                         (generate_password_hash(request.form["new"]), me["id"]))
            conn.commit()
            flash("Password changed.", "success")
            return redirect(url_for("student.profile"))
        return render_template("student/password.html", errors=errors), 422
    return render_template("student/password.html", errors=errors)
