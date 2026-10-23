"""
apply_flow.py - the admission form, in five steps, for logged-in students.

  1 Personal details   \\
  2 Contact and address  >  one page, shown a step at a time          /admission/apply
  3 Education and programme /
  4 Documents (upload, optional but recommended)                      /admission/apply/documents
  5 Review and submit (the same layout that prints)                   /admission/apply/review

Progress is saved as a draft at every step (one draft per student), so a student can leave and
come back from the dashboard. Files uploaded during the draft are kept in `draft_documents` and
are moved onto the application when it is submitted.
"""
import io
import json
import re
import secrets
import sqlite3
from functools import wraps

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

import mailer
import security
import site_data
import validators
from audit import audit
from db import get_db

FIELDS = ("full_name", "father_name", "mother_name", "dob", "gender", "category", "nationality", "email", "phone",
          "qualification", "percentage", "course_code", "address", "city", "state", "pincode")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
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
    """Take what was typed, trimmed and length-limited, without judging it (used for 'Save draft')."""
    return {f: re.sub(r"\s+", " ", (form.get(f) or "").strip())[:200] for f in FIELDS}


def _prefill(conn, me, args, courses):
    """A starting point for a new draft: the last application, otherwise the profile."""
    last = conn.execute("SELECT * FROM admissions WHERE student_id = ? ORDER BY id DESC LIMIT 1", (me["id"],)).fetchone()
    if last:
        values = {k: ("" if last[k] is None else str(last[k])) for k in FIELDS if k != "course_code"}
    else:
        values = {"full_name": me["full_name"], "email": me["email"], "phone": me["phone"] or "", "nationality": "Indian"}
    code = (args.get("course") or "").strip()
    match = next((c["code"] for c in courses if code in (c["code"], c["slug"])), "")
    values["course_code"] = match
    values.setdefault("nationality", "Indian")
    return values


def _validated(conn, sid):
    """Validate the saved draft. Returns (values, errors, course)."""
    raw = _load(conn, sid)
    course = conn.execute("SELECT * FROM courses WHERE code = ? AND is_published = 1", (raw.get("course_code", ""),)).fetchone()
    values, errors = validators.validate_application(dict(raw, declaration="yes"), course)
    if not errors and conn.execute(
            """SELECT 1 FROM admissions WHERE email = ? AND course_code = ? AND status IN ('Pending', 'Under Review')""",
            (values["email"], course["code"])).fetchone():
        errors["email"] = ("You or someone using this email already has an open application for this programme. "
                           "Check your dashboard, or use a different programme.")
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
        if not errors and conn.execute(
                "SELECT 1 FROM admissions WHERE email = ? AND course_code = ? AND status IN ('Pending', 'Under Review')",
                (values["email"], course["code"])).fetchone():
            errors["email"] = "You already have an open application for this programme with this email."
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
        return send_file(io.BytesIO(doc["data"]), mimetype=doc["mime"], as_attachment=True, download_name=doc["filename"])

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
                               missing=[n for n in need if n not in docs], preview=True)

    @app.post("/admission/apply/submit", endpoint="apply_submit")
    @_student
    def apply_submit():
        conn = get_db()
        me = security.current_student()
        if security.too_many("apply", str(me["id"]), 8, 3600):
            abort(429)
        values, errors, course = _validated(conn, me["id"])
        if errors:
            flash("Some details need fixing before you can submit.", "danger")
            return redirect(url_for("apply"))
        if request.form.get("declaration") != "yes":
            flash("Tick the declaration to submit your application.", "danger")
            return redirect(url_for("apply_review"))
        number, new_id = None, None
        for _ in range(12):
            candidate = f"MIUTM-{site_data.today_ist().year}-{secrets.randbelow(900000) + 100000}"
            try:
                cur = conn.execute(
                    """INSERT INTO admissions
                       (application_no, full_name, father_name, mother_name, gender, dob, email, phone, category,
                        nationality, qualification, percentage, course_code, course_name, address, city, state,
                        pincode, student_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (candidate, values["full_name"], values["father_name"], values["mother_name"], values["gender"],
                     values["dob"], values["email"], values["phone"], values["category"] or None, values["nationality"],
                     values["qualification"], values["percentage"], course["code"], course["name"], values["address"],
                     values["city"], values["state"], values["pincode"], me["id"]))
                new_id = cur.lastrowid
                number = candidate
                break
            except sqlite3.IntegrityError:
                conn.rollback()
        if number is None:
            abort(500)
        conn.execute("INSERT INTO admission_events (admission_id, status, note) VALUES (?,?,?)",
                     (new_id, "Pending", "Application received."))
        conn.execute("""INSERT INTO documents (admission_id, doc_type, filename, mime, size, data)
                        SELECT ?, doc_type, filename, mime, size, data FROM draft_documents WHERE student_id = ?""",
                     (new_id, me["id"]))
        conn.execute("DELETE FROM draft_documents WHERE student_id = ?", (me["id"],))
        conn.execute("DELETE FROM drafts WHERE student_id = ?", (me["id"],))
        audit("application submitted", number, course["code"], commit=False)
        conn.commit()
        mailer.application_received({"full_name": values["full_name"], "email": values["email"],
                                     "application_no": number, "course_name": course["name"]}, request.url_root)
        session["last_app"] = {"no": number, "name": values["full_name"], "course": course["name"], "email": values["email"]}
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
