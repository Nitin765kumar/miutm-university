"""
apply_flow.py - the admission form, in five steps, for logged-in students.

  1 Personal details   \
  2 Contact and address  >  one page, shown a step at a time          /admission/apply
  3 Education and programme /
  4 Documents (upload, optional but recommended)                      /admission/apply/documents
  5 Review, then Submit (and pay the application fee, if there is one) /admission/apply/review

Progress is saved as a draft at every step (one draft per student). When the student submits, an application is
created (status Payment Pending, or Submitted when there is no fee), the draft's files move onto it, and the student
goes to the payment page. Retrying never creates a second application: the database allows only one live
application per student, programme and session.
"""
import io
import json
import re
import secrets
from functools import wraps

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

import mailer
import notify
import payments
import security
import site_data
import validators
from audit import audit
from db import IntegrityError, get_db

FIELDS = ("full_name", "father_name", "mother_name", "dob", "gender", "category", "nationality", "email", "phone",
          "qualification", "percentage", "course_code", "address", "city", "state", "pincode")


def _courses(conn):
    return conn.execute("SELECT * FROM courses WHERE is_published = 1 ORDER BY sort_order, id").fetchall()


def _load(conn, sid):
    row = conn.execute("SELECT data FROM drafts WHERE student_id = ?", (sid,)).fetchone()
    try:
        return json.loads(row["data"]) if row else {}
    except ValueError:
        return {}


def _store(conn, sid, values):
    clean = {k: values.get(k, "") for k in FIELDS}
    conn.execute("INSERT INTO drafts (student_id, data) VALUES (?, ?) "
                 "ON CONFLICT(student_id) DO UPDATE SET data = excluded.data, updated_at = datetime('now')",
                 (sid, json.dumps(clean)))
    conn.commit()


def _raw(form):
    """What was typed, trimmed and length-limited, without judging it (used for 'Save draft')."""
    return {f: re.sub(r"\s+", " ", (form.get(f) or "").strip())[:200] for f in FIELDS}


def _prefill(conn, me, args, courses):
    last = conn.execute("SELECT * FROM admissions WHERE student_id = ? ORDER BY id DESC LIMIT 1", (me["id"],)).fetchone()
    if last:
        values = {k: ("" if last[k] is None else str(last[k])) for k in FIELDS if k != "course_code"}
    else:
        values = {"full_name": me["full_name"], "email": me["email"], "phone": me["phone"] or "", "nationality": "Indian"}
    code = (args.get("course") or "").strip()
    values["course_code"] = next((c["code"] for c in courses if code in (c["code"], c["slug"])), "")
    values.setdefault("nationality", "Indian")
    return values


def live_application(conn, student_id, course_code):
    """The student's open application for this programme and session, if any (the duplicate rule)."""
    return conn.execute(
        "SELECT application_no, status FROM admissions WHERE student_id = ? AND course_code = ? AND session = ? "
        "AND status NOT IN ('Cancelled', 'Rejected')",
        (student_id, course_code, site_data.current_cycle()["session"])).fetchone()


def _duplicate_message(row):
    return (f"You already have an application for this programme in this session ({row['application_no']}, {row['status']}). "
            "Open it from your dashboard. You can apply again only if it is cancelled or rejected.")


def _validated(conn, sid):
    raw = _load(conn, sid)
    course = conn.execute("SELECT * FROM courses WHERE code = ? AND is_published = 1", (raw.get("course_code", ""),)).fetchone()
    values, errors = validators.validate_application(dict(raw, declaration="yes"), course)
    if not errors:
        dup = live_application(conn, sid, course["code"])
        if dup:
            errors["course_code"] = _duplicate_message(dup)
    return values, errors, course


def _student(view):
    """Applying needs a student account, so progress can be saved and documents uploaded."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if security.current_student() is None:
            security.remember_destination()
            flash("Create a free student account or log in to apply. It lets you save your progress and upload documents.", "info")
            return redirect(url_for("student.login"))
        if site_data.admissions_state() != "open":
            flash("Applications are not open right now.", "danger")
            return redirect(url_for("student.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _draft_docs(conn, sid):
    return {d["doc_type"]: d for d in conn.execute(
        "SELECT id, doc_type, filename, size, uploaded_at FROM draft_documents WHERE student_id = ?", (sid,))}


def _preview_record(values, course):
    return dict(values, course_name=course["name"], course_code=course["code"], application_no=None,
                created_at=None, status="Draft")


def register(app):
    # ----------------------------------------------------------------- step 1-3
    @app.route("/admission/apply", methods=["GET", "POST"], endpoint="apply")
    @_student
    def apply():
        conn = get_db()
        me = security.current_student()
        courses = _courses(conn)
        ctx = dict(courses=courses, states=site_data.STATES, genders=site_data.GENDERS,
                   categories=site_data.CATEGORIES, qualifications=site_data.QUALIFICATIONS)
        if request.method == "GET":
            values = _load(conn, me["id"]) or _prefill(conn, me, request.args, courses)
            code = (request.args.get("course") or "").strip()
            hit = next((c["code"] for c in courses if code in (c["code"], c["slug"])), "")
            if hit and not values.get("course_code"):
                values["course_code"] = hit
            try:
                start = int(request.args.get("step", 0))
            except ValueError:
                start = 0
            return render_template("apply.html", values=values, errors={}, start=start, **ctx)

        raw = _raw(request.form)
        action = request.form.get("action")
        try:
            step = int(request.form.get("step", 0))
        except ValueError:
            step = 0
        _store(conn, me["id"], raw)               # nothing typed is ever lost
        if action == "save":
            flash("Draft saved. You can finish it later from your dashboard.", "success")
            return redirect(url_for("apply", step=step))

        course = conn.execute("SELECT * FROM courses WHERE code = ? AND is_published = 1", (raw["course_code"],)).fetchone()
        values, errors = validators.validate_application(dict(raw, declaration="yes"), course)
        if not errors:
            dup = live_application(conn, me["id"], course["code"])
            if dup:
                errors["course_code"] = _duplicate_message(dup)
        if errors:
            return render_template("apply.html", values=raw, errors=errors, start=step, **ctx), 422
        _store(conn, me["id"], dict(raw, **{k: str(v) for k, v in values.items() if k in FIELDS}))
        return redirect(url_for("apply_documents"))

    # ----------------------------------------------------------------- step 4
    @app.route("/admission/apply/documents", methods=["GET", "POST"], endpoint="apply_documents")
    @_student
    def apply_documents():
        conn = get_db()
        me = security.current_student()
        values, errors, course = _validated(conn, me["id"])
        if errors:
            flash("Finish the details first. We saved what you typed.", "info")
            return redirect(url_for("apply"))
        if request.method == "POST":
            if security.too_many("draft-upload", str(me["id"]), 40, 3600):
                abort(429)
            saved, problems = 0, []
            existing = _draft_docs(conn, me["id"])
            for idx, kind in enumerate(site_data.DOC_TYPES):
                f = request.files.get(f"file-{idx}")
                if f is None or not f.filename:
                    continue
                data, mime, name, error = validators.check_upload(f, kind)
                if error:
                    problems.append(f"{kind}: {error}")
                    continue
                if kind in existing:
                    conn.execute("DELETE FROM draft_documents WHERE id = ?", (existing[kind]["id"],))
                conn.execute("INSERT INTO draft_documents (student_id, doc_type, filename, mime, size, data) VALUES (?,?,?,?,?,?)",
                             (me["id"], kind, name, mime, len(data), data))
                saved += 1
            conn.commit()
            if saved:
                flash(f"{saved} document{'s' if saved != 1 else ''} saved.", "success")
            for p in problems:
                flash(p, "danger")
            if not saved and not problems and request.form.get("go") != "review":
                flash("Choose at least one file to save.", "info")
            if request.form.get("go") == "review" and not problems:
                return redirect(url_for("apply_review"))
            return redirect(url_for("apply_documents"))
        need = site_data.required_docs(values["qualification"], values["category"])
        return render_template("apply_documents.html", values=values, course=course, need=need,
                               optional=[d for d in site_data.DOC_TYPES if d not in need],
                               kinds=list(enumerate(site_data.DOC_TYPES)), docs=_draft_docs(conn, me["id"]))

    @app.post("/admission/apply/documents/<int:doc_id>/delete", endpoint="apply_doc_delete")
    @_student
    def apply_doc_delete(doc_id):
        conn = get_db()
        conn.execute("DELETE FROM draft_documents WHERE id = ? AND student_id = ?", (doc_id, security.current_student()["id"]))
        conn.commit()
        flash("Document removed.", "success")
        return redirect(url_for("apply_documents"))

    @app.get("/admission/apply/documents/<int:doc_id>", endpoint="apply_doc_download")
    @_student
    def apply_doc_download(doc_id):
        doc = get_db().execute("SELECT * FROM draft_documents WHERE id = ? AND student_id = ?",
                               (doc_id, security.current_student()["id"])).fetchone()
        if doc is None:
            abort(404)
        return send_file(io.BytesIO(bytes(doc["data"])), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])

    # ----------------------------------------------------------------- step 5
    @app.get("/admission/apply/review", endpoint="apply_review")
    @_student
    def apply_review():
        conn = get_db()
        me = security.current_student()
        values, errors, course = _validated(conn, me["id"])
        if errors:
            flash("Some details need fixing before you can submit.", "danger")
            return redirect(url_for("apply"))
        need = site_data.required_docs(values["qualification"], values["category"])
        docs = _draft_docs(conn, me["id"])
        return render_template("apply_review.html", a=_preview_record(values, course), need=need, docs=docs,
                               missing=[n for n in need if n not in docs], preview=True, fee=site_data.application_fee(),
                               unverified=mailer.email_enabled() and not me["email_verified"])

    @app.post("/admission/apply/submit", endpoint="apply_submit")
    @_student
    def apply_submit():
        conn = get_db()
        me = security.current_student()
        if security.too_many("apply", str(me["id"]), 8, 3600):
            abort(429)
        if mailer.email_enabled() and not me["email_verified"]:
            flash("Confirm your email address before you submit. We sent you a link; you can ask for another on your dashboard.", "danger")
            return redirect(url_for("apply_review"))
        values, errors, course = _validated(conn, me["id"])
        if errors:
            flash(errors.get("course_code") or "Some details need fixing before you can submit.", "danger")
            return redirect(url_for("apply"))
        if request.form.get("declaration") != "yes":
            flash("Tick the declaration to submit your application.", "danger")
            return redirect(url_for("apply_review"))

        fee = site_data.application_fee()
        status = "Payment Pending" if fee > 0 else "Submitted"
        session_label = site_data.current_cycle()["session"]
        number = new_id = None
        for _ in range(12):
            candidate = f"MIUTM-{site_data.today_ist().year}-{secrets.randbelow(900000) + 100000}"
            try:
                cur = conn.execute(
                    """INSERT INTO admissions
                       (application_no, full_name, father_name, mother_name, gender, dob, email, phone, category,
                        nationality, qualification, percentage, course_code, course_name, address, city, state,
                        pincode, student_id, status, session, payment_status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (candidate, values["full_name"], values["father_name"], values["mother_name"], values["gender"],
                     values["dob"], values["email"], values["phone"], values["category"] or None, values["nationality"],
                     values["qualification"], values["percentage"], course["code"], course["name"], values["address"],
                     values["city"], values["state"], values["pincode"], me["id"], status, session_label,
                     "Unpaid" if fee > 0 else "Waived"))
                new_id, number = cur.lastrowid, candidate
                break
            except IntegrityError:
                conn.rollback()
                dup = live_application(conn, me["id"], course["code"])
                if dup:  # the database's own duplicate rule (a double click, two tabs)
                    flash(_duplicate_message(dup), "danger")
                    return redirect(url_for("student.application", application_no=dup["application_no"]))
        if number is None:
            abort(500)
        conn.execute("INSERT INTO admission_events (admission_id, status, changed_by, note) VALUES (?,?,?,?)",
                     (new_id, status, me["email"], "Application created." if fee > 0 else "Application received."))
        conn.execute("""INSERT INTO documents (admission_id, doc_type, filename, mime, size, data)
                        SELECT ?, doc_type, filename, mime, size, data FROM draft_documents WHERE student_id = ?""",
                     (new_id, me["id"]))
        for d in conn.execute("SELECT doc_type FROM documents WHERE admission_id = ?", (new_id,)).fetchall():
            conn.execute("INSERT INTO document_events (admission_id, doc_type, action, actor) VALUES (?,?,?,?)",
                         (new_id, d["doc_type"], "Uploaded", me["email"]))
        conn.execute("DELETE FROM draft_documents WHERE student_id = ?", (me["id"],))
        conn.execute("DELETE FROM drafts WHERE student_id = ?", (me["id"],))
        admission = conn.execute("SELECT * FROM admissions WHERE id = ?", (new_id,)).fetchone()
        audit("application created", number, course["code"], commit=False)
        session["last_app"] = {"no": number, "name": values["full_name"], "course": course["name"], "email": values["email"]}
        if fee > 0:
            order = payments.get_or_create(conn, admission, "Application Fee", fee)  # commits
            return redirect(url_for("student.payment", order_id=order["order_id"]))
        conn.execute("UPDATE admissions SET submitted_at = datetime('now') WHERE id = ?", (new_id,))
        notify.notify(me["id"], "Application submitted", f"{number} for {course['name']}.", url_for("student.application", application_no=number), "status")
        conn.commit()
        mailer.application_received(admission, request.url_root)
        return redirect(url_for("apply_success"))

    @app.post("/admission/apply/discard", endpoint="apply_discard")
    @security.student_required
    def apply_discard():
        conn = get_db()
        sid = security.current_student()["id"]
        conn.execute("DELETE FROM draft_documents WHERE student_id = ?", (sid,))
        conn.execute("DELETE FROM drafts WHERE student_id = ?", (sid,))
        conn.commit()
        flash("Your draft was discarded.", "success")
        return redirect(url_for("student.dashboard"))

    # ----------------------------------------------------------------- done
    @app.get("/admission/success", endpoint="apply_success")
    @security.student_required
    def apply_success():
        info = session.get("last_app")
        record = None
        if info:
            record = get_db().execute("SELECT * FROM admissions WHERE application_no = ? AND student_id = ?",
                                      (info["no"], security.current_student()["id"])).fetchone()
        if record is None:
            return redirect(url_for("student.dashboard"))
        return render_template("apply_success.html", info=info, a=record)
