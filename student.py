"""
student.py - student accounts and everything a student does after signing up, under /student.

Account (register, log in, email verification, password reset), dashboard with summary and timeline, applications,
documents, payments and receipts, notifications, and the downloadable letters.
"""
import io
from urllib.parse import urlparse

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, send_file, session, url_for)
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


def _serializer(salt):
    from flask import current_app
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _link_application(student_id, application_no):
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
    if last:
        _link_application(student["id"], last["no"])
    return nxt


def _own(application_no):
    row = get_db().execute(
        """SELECT a.*, c.slug AS course_slug, c.level AS course_level, c.admission_fee AS admission_fee
           FROM admissions a LEFT JOIN courses c ON c.code = a.course_code
           WHERE a.application_no = ? AND a.student_id = ?""",
        (application_no.upper(), security.current_student()["id"])).fetchone()
    if row is None:
        abort(404)
    return row


def _own_payment(order_id):
    row = get_db().execute(
        """SELECT p.*, a.application_no, a.course_name, a.status AS app_status FROM payments p
           JOIN admissions a ON a.id = p.admission_id WHERE p.order_id = ? AND p.student_id = ?""",
        (order_id, security.current_student()["id"])).fetchone()
    if row is None:
        abort(404)
    return row


def _send_verification(student):
    token = _serializer("student-verify").dumps({"id": student["id"], "e": student["email"]})
    return mailer.email_verification(student, url_for("student.verify", token=token, _external=True))


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
            verified = 0 if mailer.email_enabled() else 1   # without email there is no way to verify
            cur = conn.execute(
                "INSERT INTO students (email, password_hash, full_name, phone, email_verified) VALUES (?,?,?,?,?)",
                (values["email"], generate_password_hash(request.form["password"]), values["full_name"],
                 values["phone"] or None, verified))
            conn.commit()
            student = conn.execute("SELECT * FROM students WHERE id = ?", (cur.lastrowid,)).fetchone()
            nxt = _sign_in(student, remember=True)
            audit("student register", student["email"])
            if not verified:
                _send_verification(student)
                flash("Your account is ready. We sent a link to confirm your email address.", "success")
            else:
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
        ok = check_password_hash(student["password_hash"] if student else _DUMMY_HASH, request.form.get("password") or "")
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


@student_bp.get("/verify/<token>")
def verify(token):
    try:
        data = _serializer("student-verify").loads(token, max_age=3 * 24 * 3600)
    except (BadSignature, SignatureExpired):
        flash("That confirmation link is invalid or has expired. Log in and ask for a new one.", "danger")
        return redirect(url_for("student.login"))
    conn = get_db()
    conn.execute("UPDATE students SET email_verified = 1 WHERE id = ? AND email = ?", (data["id"], data["e"]))
    conn.commit()
    flash("Your email address is confirmed. Thank you.", "success")
    return redirect(url_for("student.dashboard") if security.current_student() else url_for("student.login"))


@student_bp.post("/resend-verification")
@security.student_required
def resend_verification():
    me = security.current_student()
    if me["email_verified"]:
        flash("Your email address is already confirmed.", "info")
    elif not mailer.email_enabled():
        flash("Email is not set up on this server, so a link cannot be sent. Contact the admissions office.", "danger")
    elif security.too_many("verify", str(me["id"]), 4, 3600):
        abort(429)
    else:
        _send_verification(me)
        flash("We sent a new confirmation link.", "success")
    return redirect(request.referrer if _safe_next(urlparse(request.referrer or "").path) else url_for("student.dashboard"))


# ---------------------------------------------------------------------------
# Forgot / reset password (works when email is switched on)
# ---------------------------------------------------------------------------
@student_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent = False
    if request.method == "POST" and mailer.email_enabled():
        if security.too_many("forgot", security.client_ip(), 5, 3600):
            abort(429)
        email = (request.form.get("email") or "").strip().lower()[:120]
        student = get_db().execute("SELECT * FROM students WHERE email = ? AND is_active = 1", (email,)).fetchone()
        if student:
            token = _serializer("student-reset").dumps({"id": student["id"], "h": student["password_hash"][-12:]})
            mailer.password_reset(student, url_for("student.reset", token=token, _external=True))
        sent = True  # same answer whether or not the email has an account
    return render_template("student/forgot.html", sent=sent, email_on=mailer.email_enabled())


@student_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = _serializer("student-reset").loads(token, max_age=3600)
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
            errors["confirm"] = "Passwords do not match."
        else:
            conn.execute("UPDATE students SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), student["id"]))
            conn.commit()
            security.sign_out_student()
            flash("Password changed. Log in with your new password.", "success")
            return redirect(url_for("student.login"))
        return render_template("student/reset.html", bad=False, errors=errors), 422
    return render_template("student/reset.html", bad=False, errors=errors)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _doc_progress(conn, a):
    need = site_data.required_docs(a["qualification"], a["category"])
    have = {d["doc_type"]: d["status"] for d in conn.execute("SELECT doc_type, status FROM documents WHERE admission_id = ?", (a["id"],))}
    return {"need": len(need), "uploaded": len([n for n in need if n in have]),
            "verified": len([n for n in need if have.get(n) == "Verified"]),
            "rejected": len([n for n in need if have.get(n) == "Rejected"])}


@student_bp.get("/dashboard")
@security.student_required
def dashboard():
    import json
    conn = get_db()
    me = security.current_student()
    apps = conn.execute(
        """SELECT a.*, c.slug AS course_slug, c.admission_fee AS admission_fee FROM admissions a
           LEFT JOIN courses c ON c.code = a.course_code WHERE a.student_id = ? ORDER BY a.id DESC""", (me["id"],)).fetchall()
    progress = {a["id"]: _doc_progress(conn, a) for a in apps}
    live = [a for a in apps if a["status"] not in site_data.CLOSED]
    primary = (live or apps or [None])[0]
    timeline = None
    if primary is not None:
        docs = conn.execute("SELECT doc_type, status FROM documents WHERE admission_id = ?", (primary["id"],)).fetchall()
        timeline = workflow.timeline(primary, site_data.required_docs(primary["qualification"], primary["category"]), docs)
    pays = conn.execute(
        """SELECT p.*, a.application_no, a.course_code FROM payments p JOIN admissions a ON a.id = p.admission_id
           WHERE p.student_id = ? ORDER BY p.id DESC""", (me["id"],)).fetchall()
    notices = conn.execute("SELECT * FROM notices WHERE is_published = 1 ORDER BY published_on DESC, id DESC LIMIT 3").fetchall()
    unread = conn.execute("SELECT * FROM notifications WHERE student_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 4", (me["id"],)).fetchall()
    draft = None
    row = conn.execute("SELECT data, updated_at FROM drafts WHERE student_id = ?", (me["id"],)).fetchone()
    if row:
        try:
            data = json.loads(row["data"])
        except ValueError:
            data = {}
        course = conn.execute("SELECT name FROM courses WHERE code = ?", (data.get("course_code", ""),)).fetchone()
        draft = {"course": course["name"] if course else None, "updated": row["updated_at"],
                 "files": conn.execute("SELECT COUNT(*) FROM draft_documents WHERE student_id = ?", (me["id"],)).fetchone()[0]}
    return render_template("student/dashboard.html", me=me, apps=apps, progress=progress, notices=notices, draft=draft,
                           primary=primary, timeline=timeline, payments=pays, unread=unread,
                           status_next=site_data.STATUS_NEXT, withdrawable=site_data.WITHDRAWABLE,
                           verify_needed=mailer.email_enabled() and not me["email_verified"])


@student_bp.get("/applications/<application_no>")
@security.student_required
def application(application_no):
    a = _own(application_no)
    conn = get_db()
    events = conn.execute("SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id DESC", (a["id"],)).fetchall()
    docs = {d["doc_type"]: d for d in conn.execute(
        "SELECT id, doc_type, filename, size, status, note, uploaded_at, reviewed_at FROM documents WHERE admission_id = ?", (a["id"],))}
    required = site_data.required_docs(a["qualification"], a["category"])
    pays = conn.execute("SELECT * FROM payments WHERE admission_id = ? ORDER BY id", (a["id"],)).fetchall()
    timeline = workflow.timeline(a, required, list(docs.values()))
    return render_template("student/application.html", a=a, events=events, docs=docs, required=required,
                           optional=[d for d in site_data.DOC_TYPES if d not in required], timeline=timeline, payments=pays,
                           status_help=site_data.STATUS_HELP, status_next=site_data.STATUS_NEXT,
                           can_edit=a["status"] in site_data.EDITABLE, can_withdraw=a["status"] in site_data.WITHDRAWABLE,
                           can_upload=a["status"] not in site_data.CLOSED,
                           has_letter=a["status"] in ("Approved", "Admission Confirmed"),
                           can_pay_admission=a["status"] in ("Selected", "Admission Fee Pending") and (a["admission_fee"] or 0) > 0)


@student_bp.route("/applications/<application_no>/edit", methods=["GET", "POST"])
@security.student_required
def edit_application(application_no):
    a = _own(application_no)
    if a["status"] not in site_data.EDITABLE:
        flash("This application can no longer be edited online. Contact the admissions office for changes.", "danger")
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
        if not errors and course["code"] != a["course_code"] and conn.execute(
                "SELECT 1 FROM admissions WHERE student_id = ? AND course_code = ? AND session = ? AND id != ? "
                "AND status NOT IN ('Cancelled', 'Rejected')", (a["student_id"], course["code"], a["session"], a["id"])).fetchone():
            errors["course_code"] = "You already have an application for that programme in this session."
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
        conn.execute("INSERT INTO admission_events (admission_id, status, changed_by, note) VALUES (?,?,?,?)",
                     (a["id"], a["status"], me_email(), "Details updated by the applicant."))
        audit("student edit", a["application_no"], commit=False)
        conn.commit()
        flash("Your application was updated.", "success")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    return render_template("student/edit.html", values=dict(a), errors={}, **ctx)


def me_email():
    return security.current_student()["email"]


@student_bp.post("/applications/<application_no>/withdraw")
@security.student_required
def withdraw(application_no):
    a = _own(application_no)
    if a["status"] not in site_data.WITHDRAWABLE:
        flash("This application can no longer be withdrawn.", "danger")
    else:
        workflow.set_status(a, "Cancelled", note="Withdrawn by the applicant.")
        flash("Your application was withdrawn. Any refund is handled by the admissions office under the refund policy.", "success")
    return redirect(url_for("student.application", application_no=a["application_no"]))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@student_bp.post("/applications/<application_no>/documents")
@security.student_required
def upload_document(application_no):
    a = _own(application_no)
    back = redirect(url_for("student.application", application_no=a["application_no"]) + "#documents")
    if a["status"] in site_data.CLOSED:
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
    old = conn.execute("SELECT id, status FROM documents WHERE admission_id = ? AND doc_type = ?", (a["id"], doc_type)).fetchone()
    if old and old["status"] == "Verified":
        flash(f"Your {doc_type.lower()} is already verified, so it cannot be replaced.", "danger")
        return back
    if old:
        conn.execute("DELETE FROM documents WHERE id = ?", (old["id"],))
    conn.execute("INSERT INTO documents (admission_id, doc_type, filename, mime, size, data) VALUES (?,?,?,?,?,?)",
                 (a["id"], doc_type, name, mime, len(data), data))
    conn.execute("INSERT INTO document_events (admission_id, doc_type, action, actor) VALUES (?,?,?,?)",
                 (a["id"], doc_type, "Replaced" if old else "Uploaded", me_email()))
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
        conn.execute("INSERT INTO document_events (admission_id, doc_type, action, actor) VALUES (?,?,?,?)",
                     (a["id"], doc["doc_type"], "Removed", me_email()))
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
    return send_file(io.BytesIO(bytes(doc["data"])), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@student_bp.get("/payments/<order_id>")
@security.student_required
def payment(order_id):
    p = _own_payment(order_id)
    events = get_db().execute("SELECT * FROM payment_events WHERE payment_id = ? ORDER BY id DESC", (p["id"],)).fetchall()
    return render_template("student/payment.html", p=p, events=events, methods=site_data.PAYMENT_METHODS,
                           simulate_ok=site_data.DEMO_MODE,
                           verify_needed=p["purpose"] == "Application Fee" and mailer.email_enabled()
                           and not security.current_student()["email_verified"])


@student_bp.post("/payments/<order_id>/pay")
@security.student_required
def pay(order_id):
    p = _own_payment(order_id)
    conn = get_db()
    me = security.current_student()
    if security.too_many("pay", str(me["id"]), 20, 3600):
        abort(429)
    if p["purpose"] == "Application Fee" and mailer.email_enabled() and not me["email_verified"]:
        flash("Confirm your email address before paying. Use the link we sent you, or ask for a new one on your dashboard.", "danger")
        return redirect(url_for("student.payment", order_id=order_id))
    method = request.form.get("method")
    if method not in site_data.PAYMENT_METHODS:
        flash("Choose a payment method.", "danger")
        return redirect(url_for("student.payment", order_id=order_id))
    outcome = payments.run_demo(conn, p, method, simulate_failure=site_data.DEMO_MODE and request.form.get("simulate") == "fail")
    flash({"success": "Payment successful. Your receipt is ready below.",
           "failed": "Payment failed. Nothing was charged. You can try again.",
           "busy": "This payment is already being processed. Refresh in a moment.",
           "paid": "This payment is already complete."}[outcome], "success" if outcome in ("success", "paid") else "danger")
    return redirect(url_for("student.payment", order_id=order_id))


@student_bp.post("/payments/<order_id>/cancel")
@security.student_required
def cancel_payment(order_id):
    p = _own_payment(order_id)
    if payments.cancel(get_db(), p):
        flash("Payment cancelled. Your application stays saved; you can pay whenever you are ready.", "info")
    return redirect(url_for("student.payment", order_id=order_id))


@student_bp.get("/payments/<order_id>/receipt.pdf")
@security.student_required
def payment_receipt(order_id):
    p = _own_payment(order_id)
    if p["status"] not in ("Successful", "Refunded"):
        flash("A receipt is available after a successful payment.", "info")
        return redirect(url_for("student.payment", order_id=order_id))
    a = get_db().execute("SELECT * FROM admissions WHERE id = ?", (p["admission_id"],)).fetchone()
    return _pdf(pdfdocs.payment_receipt_pdf(site_data.current_site(), a, p, site_data.DEMO_MODE), f"receipt-{p['order_id']}.pdf")


@student_bp.post("/applications/<application_no>/admission-fee")
@security.student_required
def start_admission_fee(application_no):
    a = _own(application_no)
    if a["status"] not in ("Selected", "Admission Fee Pending") or not (a["admission_fee"] or 0) > 0:
        flash("There is no admission fee to pay for this application right now.", "info")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    conn = get_db()
    order = payments.get_or_create(conn, a, "Admission Fee", a["admission_fee"])
    if a["status"] == "Selected":
        workflow.set_status(a, "Admission Fee Pending", note="Admission fee requested.")
    return redirect(url_for("student.payment", order_id=order["order_id"]))


# ---------------------------------------------------------------------------
# PDFs and printable pages
# ---------------------------------------------------------------------------
def _pdf(data, name):
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename={name}",
                                                              "Cache-Control": "no-store"})


@student_bp.get("/applications/<application_no>/receipt.pdf")
@security.student_required
def application_receipt(application_no):
    a = _own(application_no)
    pay_row = get_db().execute("SELECT * FROM payments WHERE admission_id = ? AND purpose = 'Application Fee'", (a["id"],)).fetchone()
    return _pdf(pdfdocs.application_receipt_pdf(site_data.current_site(), a, pay_row, site_data.DEMO_MODE), f"application-{a['application_no']}.pdf")


@student_bp.get("/applications/<application_no>/admission-letter.pdf")
@security.student_required
def admission_letter(application_no):
    a = _own(application_no)
    if a["status"] not in ("Approved", "Admission Confirmed"):
        flash("Your admission letter is available once your admission is approved.", "info")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    ctx = workflow.offer_context(get_db(), a)
    return _pdf(pdfdocs.admission_letter_pdf(site_data.current_site(), a, ctx["course"], ctx["docs_needed"], ctx["counselling"],
                                             ctx["classes_begin"], site_data.DEMO_MODE), f"admission-letter-{a['application_no']}.pdf")


@student_bp.get("/applications/<application_no>/confirmation-letter.pdf")
@security.student_required
def confirmation_letter(application_no):
    a = _own(application_no)
    if a["status"] != "Admission Confirmed":
        flash("The confirmation letter is available once your admission is confirmed.", "info")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    ctx = workflow.offer_context(get_db(), a)
    return _pdf(pdfdocs.confirmation_letter_pdf(site_data.current_site(), a, ctx["course"], ctx["classes_begin"], site_data.DEMO_MODE),
                f"confirmation-{a['application_no']}.pdf")


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
    if a["status"] not in ("Approved", "Admission Confirmed"):
        flash("Your admission letter is available once your admission is approved.", "info")
        return redirect(url_for("student.application", application_no=a["application_no"]))
    return render_template("print_page.html", a=a, partial="partials/_offer_letter.html",
                           back_url=url_for("student.application", application_no=a["application_no"]),
                           **workflow.offer_context(get_db(), a))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@student_bp.get("/notifications")
@security.student_required
def notifications():
    rows = get_db().execute("SELECT * FROM notifications WHERE student_id = ? ORDER BY id DESC LIMIT 100",
                            (security.current_student()["id"],)).fetchall()
    return render_template("student/notifications.html", rows=rows)


@student_bp.post("/notifications/<int:nid>/read")
@security.student_required
def notification_read(nid):
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND student_id = ?", (nid, security.current_student()["id"]))
    conn.commit()
    return redirect(url_for("student.notifications"))


@student_bp.post("/notifications/read-all")
@security.student_required
def notifications_read_all():
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE student_id = ?", (security.current_student()["id"],))
    conn.commit()
    return redirect(url_for("student.notifications"))


# ---------------------------------------------------------------------------
# Claim an application made without an account (older versions)
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
        row = (conn.execute("SELECT * FROM admissions WHERE application_no = ? AND dob = ?", (number, dob)).fetchone()
               if validators.clean_date(dob) else None)
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
            conn.execute("UPDATE students SET full_name = ?, phone = ? WHERE id = ?", (values["full_name"], values["phone"] or None, me["id"]))
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
        errors = validators.validate_student_password_change(ok, request.form.get("new") or "", request.form.get("confirm") or "")
        if not errors:
            conn = get_db()
            conn.execute("UPDATE students SET password_hash = ? WHERE id = ?", (generate_password_hash(request.form["new"]), me["id"]))
            conn.commit()
            flash("Password changed.", "success")
            return redirect(url_for("student.profile"))
        return render_template("student/password.html", errors=errors), 422
    return render_template("student/password.html", errors=errors)
