"""
admin_more.py - the rest of the staff area (all routes are added to the same /admin blueprint):
content manager, staff accounts, reports, activity log and database backup.
Most of these are administrator-only.
"""
import io
import os
import re
import sqlite3
import tempfile
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.security import generate_password_hash

import security
import settings as site_settings
import site_data
import validators
from admin import admin_bp, admin_only
from audit import audit
from db import get_db

# ---------------------------------------------------------------------------
# Content manager: one generic set of pages for five kinds of content
# ---------------------------------------------------------------------------
LEVELS = ["Undergraduate", "Postgraduate", "Diploma", "Certificate"]
AUDIENCE_TOKENS = {"s12m", "s12o", "gcs", "gany", "short"}
NOTICE_CATEGORIES = ["Admissions", "Scholarships", "Campus", "Academics", "Events", "General"]


def F(name, label, type_, **kw):
    return dict(name=name, label=label, type=type_, **kw)


CONTENT = {
    "programmes": dict(
        table="courses", title="Programmes", singular="programme", order="sort_order, id", name_field="name",
        columns=[("code", "Code"), ("name", "Name"), ("level", "Level"), ("seats", "Seats")],
        fields=[
            F("code", "Code", "text", max=20, readonly_on_edit=True, hint="Short and unique, like MBA. It cannot be changed later."),
            F("name", "Name", "text", max=120, span2=True),
            F("level", "Level", "select", choices=LEVELS),
            F("school", "School", "text", max=80),
            F("duration", "Duration", "text", max=30, hint="For example: 3 years or 6 months."),
            F("seats", "Seats", "int", min=0, max=5000),
            F("fee", "Fee in rupees", "int", min=0, max=10000000),
            F("fee_period", "Fee is charged", "select", choices=["per year", "total"]),
            F("min_percent", "Minimum marks (%)", "int", min=0, max=100, hint="0 means no minimum."),
            F("sort_order", "Display order", "int", min=0, max=999, required=False),
            F("eligibility", "Eligibility text", "textarea", max=300, span2=True),
            F("accepts", "Accepted qualifications", "text", max=200, span2=True,
              hint="Comma separated, from: " + ", ".join(site_data.QUALIFICATIONS)),
            F("audience", "Programme finder tags", "text", max=40, span2=True,
              hint="Space separated from: s12m (12th with Maths), s12o (12th without), gcs (degree in CS/IT), gany (any degree), short (short course)."),
            F("summary", "Short summary", "textarea", max=300, span2=True),
            F("topics", "Topics", "textarea", max=600, span2=True, hint="Comma separated."),
            F("is_published", "Show on the website", "bool"),
        ]),
    "notices": dict(
        table="notices", title="Notices", singular="notice", order="published_on DESC, id DESC", name_field="title",
        columns=[("published_on", "Date"), ("title", "Title"), ("category", "Category")],
        fields=[
            F("title", "Title", "text", max=120, span2=True),
            F("category", "Category", "select", choices=NOTICE_CATEGORIES),
            F("published_on", "Date", "date"),
            F("body", "Text", "textarea", max=600, span2=True),
            F("is_published", "Show on the website", "bool"),
        ]),
    "events": dict(
        table="events", title="Events", singular="event", order="starts_on DESC, id DESC", name_field="title",
        columns=[("starts_on", "Starts"), ("title", "Title"), ("location", "Where")],
        fields=[
            F("title", "Title", "text", max=120, span2=True),
            F("starts_on", "Starts on", "date"),
            F("ends_on", "Ends on", "date", required=False, hint="Leave blank for a one-day event."),
            F("location", "Where", "text", max=120, required=False, span2=True),
            F("description", "Description", "textarea", max=500, span2=True),
            F("is_published", "Show on the website", "bool"),
        ]),
    "faculty": dict(
        table="faculty", title="Faculty", singular="faculty member", order="id", name_field="name",
        columns=[("name", "Name"), ("designation", "Designation"), ("school", "School")],
        fields=[
            F("name", "Name", "text", max=80),
            F("designation", "Designation", "text", max=80),
            F("school", "School", "text", max=80),
            F("specialization", "Specialisation", "text", max=160, span2=True),
            F("is_published", "Show on the website", "bool"),
        ]),
    "faqs": dict(
        table="faqs", title="FAQs", singular="question", order="sort_order, id", name_field="question",
        columns=[("sort_order", "Order"), ("question", "Question")],
        fields=[
            F("question", "Question", "text", max=200, span2=True),
            F("answer", "Answer", "textarea", max=800, span2=True),
            F("sort_order", "Display order", "int", min=0, max=999),
            F("is_published", "Show on the website", "bool"),
        ]),
}


def _cfg(kind):
    if kind not in CONTENT:
        abort(404)
    return CONTENT[kind]


def _parse_form(cfg, form, editing):
    values, errors = {}, {}
    for f in cfg["fields"]:
        value, err = validators.parse_content_field(f, form.get(f["name"]), editing)
        if err:
            errors[f["name"]] = err
        elif not (f.get("readonly_on_edit") and editing):
            values[f["name"]] = value
    return values, errors


def _programme_checks(values, errors, editing):
    if not editing and "code" not in errors:
        code = values["code"].upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9-]{1,19}$", code):
            errors["code"] = "Use 2 to 20 letters, numbers or dashes."
        else:
            values["code"] = code
            values["slug"] = code.lower()
    if "accepts" not in errors and values.get("accepts"):
        parts = [p.strip() for p in values["accepts"].split(",") if p.strip()]
        bad = [p for p in parts if p not in site_data.QUALIFICATIONS]
        if bad or not parts:
            errors["accepts"] = "Use only: " + ", ".join(site_data.QUALIFICATIONS)
        else:
            values["accepts"] = ",".join(parts)
    if "audience" not in errors and values.get("audience"):
        tokens = values["audience"].split()
        if not tokens or any(t not in AUDIENCE_TOKENS for t in tokens):
            errors["audience"] = "Use only: " + ", ".join(sorted(AUDIENCE_TOKENS))
        else:
            values["audience"] = " ".join(tokens)
    if values.get("sort_order") is None:
        values["sort_order"] = 99


@admin_bp.get("/content")
@admin_only
def content_index():
    conn = get_db()
    counts = {k: conn.execute(f"SELECT COUNT(*) FROM {c['table']}").fetchone()[0] for k, c in CONTENT.items()}
    return render_template("admin/content_index.html", content=CONTENT, counts=counts)


@admin_bp.get("/content/<kind>")
@admin_only
def content_list(kind):
    cfg = _cfg(kind)
    rows = get_db().execute(f"SELECT * FROM {cfg['table']} ORDER BY {cfg['order']}").fetchall()
    return render_template("admin/content_list.html", kind=kind, cfg=cfg, rows=rows)


@admin_bp.route("/content/<kind>/new", methods=["GET", "POST"])
@admin_only
def content_new(kind):
    cfg = _cfg(kind)
    values, errors = {"is_published": 1}, {}
    if request.method == "POST":
        values, errors = _parse_form(cfg, request.form, editing=False)
        if kind == "programmes":
            _programme_checks(values, errors, editing=False)
        if not errors:
            cols = list(values)
            try:
                conn = get_db()
                conn.execute(f"INSERT INTO {cfg['table']} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [values[c] for c in cols])
                audit("content add", f"{kind}", str(values.get(cfg["name_field"], "")), commit=False)
                conn.commit()
            except sqlite3.IntegrityError:
                errors["name" if kind == "programmes" else cfg["name_field"]] = "That already exists. Use a different value."
            else:
                flash(f"Added {cfg['singular']}.", "success")
                return redirect(url_for("admin.content_list", kind=kind))
        return render_template("admin/content_form.html", kind=kind, cfg=cfg, values=values, errors=errors, editing=False), 422
    return render_template("admin/content_form.html", kind=kind, cfg=cfg, values=values, errors=errors, editing=False)


@admin_bp.route("/content/<kind>/<int:rid>/edit", methods=["GET", "POST"])
@admin_only
def content_edit(kind, rid):
    cfg = _cfg(kind)
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {cfg['table']} WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        values, errors = _parse_form(cfg, request.form, editing=True)
        if kind == "programmes":
            _programme_checks(values, errors, editing=True)
        if not errors:
            cols = list(values)
            try:
                conn.execute(f"UPDATE {cfg['table']} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                             [values[c] for c in cols] + [rid])
                audit("content edit", kind, str(values.get(cfg["name_field"], rid)), commit=False)
                conn.commit()
            except sqlite3.IntegrityError:
                errors[cfg["name_field"]] = "That already exists. Use a different value."
            else:
                flash(f"Saved {cfg['singular']}.", "success")
                return redirect(url_for("admin.content_list", kind=kind))
        merged = dict(row)
        merged.update(values)
        return render_template("admin/content_form.html", kind=kind, cfg=cfg, values=merged, errors=errors, editing=True, rid=rid), 422
    return render_template("admin/content_form.html", kind=kind, cfg=cfg, values=dict(row), errors={}, editing=True, rid=rid)


@admin_bp.post("/content/<kind>/<int:rid>/toggle")
@admin_only
def content_toggle(kind, rid):
    cfg = _cfg(kind)
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {cfg['table']} WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    new = 0 if row["is_published"] else 1
    conn.execute(f"UPDATE {cfg['table']} SET is_published = ? WHERE id = ?", (new, rid))
    audit("content " + ("show" if new else "hide"), kind, str(row[cfg["name_field"]]), commit=False)
    conn.commit()
    flash(f"{cfg['singular'].capitalize()} is now {'visible' if new else 'hidden'}.", "success")
    return redirect(url_for("admin.content_list", kind=kind))


@admin_bp.post("/content/<kind>/<int:rid>/delete")
@admin_only
def content_delete(kind, rid):
    cfg = _cfg(kind)
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {cfg['table']} WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    if kind == "programmes" and conn.execute("SELECT 1 FROM admissions WHERE course_code = ?", (row["code"],)).fetchone():
        flash("This programme has applications, so it cannot be deleted. Hide it from the website instead.", "danger")
        return redirect(url_for("admin.content_list", kind=kind))
    conn.execute(f"DELETE FROM {cfg['table']} WHERE id = ?", (rid,))
    audit("content delete", kind, str(row[cfg["name_field"]]), commit=False)
    conn.commit()
    flash(f"Deleted {cfg['singular']}.", "success")
    return redirect(url_for("admin.content_list", kind=kind))


# ---------------------------------------------------------------------------
# Staff accounts
# ---------------------------------------------------------------------------
def _other_active_admins(conn, user_id):
    return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?", (user_id,)).fetchone()[0]


@admin_bp.get("/staff")
@admin_only
def staff_list():
    rows = get_db().execute("SELECT * FROM users WHERE approved = 1 ORDER BY id").fetchall()
    pending = get_db().execute("SELECT * FROM users WHERE approved = 0 ORDER BY id").fetchall()
    return render_template("admin/staff.html", rows=rows, pending=pending, roles=site_data.ROLES,
                           signup_code_on=bool(site_data.staff_signup_code()))


@admin_bp.route("/staff/new", methods=["GET", "POST"])
@admin_only
def staff_new():
    values, errors = {"role": "reviewer", "is_active": 1}, {}
    if request.method == "POST":
        values, errors = validators.validate_staff(request.form, creating=True)
        conn = get_db()
        if not errors and conn.execute("SELECT 1 FROM users WHERE username = ?", (values["username"],)).fetchone():
            errors["username"] = "That username is taken."
        if not errors:
            conn.execute("INSERT INTO users (username, password_hash, full_name, email, role, is_active) VALUES (?,?,?,?,?,?)",
                         (values["username"], generate_password_hash(request.form["password"]), values["full_name"],
                          values["email"] or None, values["role"], 1))
            audit("staff add", values["username"], values["role"], commit=False)
            conn.commit()
            flash(f"Staff account '{values['username']}' created. Share the password with them privately.", "success")
            return redirect(url_for("admin.staff_list"))
        return render_template("admin/staff_form.html", values=values, errors=errors, editing=False, roles=site_data.ROLES), 422
    return render_template("admin/staff_form.html", values=values, errors=errors, editing=False, roles=site_data.ROLES)


@admin_bp.route("/staff/<int:uid>/edit", methods=["GET", "POST"])
@admin_only
def staff_edit(uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    values, errors = dict(user), {}
    if request.method == "POST":
        values, errors = validators.validate_staff(request.form, creating=False, existing_username=user["username"])
        values["username"] = user["username"]
        values["id"] = uid
        losing_admin = user["role"] == "admin" and user["is_active"] and (values["role"] != "admin" or not values["is_active"])
        if not errors and losing_admin and _other_active_admins(conn, uid) == 0:
            errors["role"] = "This is the only active administrator. Create another administrator first."
        if not errors:
            conn.execute("UPDATE users SET full_name = ?, email = ?, role = ?, is_active = ? WHERE id = ?",
                         (values["full_name"], values["email"] or None, values["role"], values["is_active"], uid))
            audit("staff edit", user["username"], f"{values['role']}, active={values['is_active']}", commit=False)
            conn.commit()
            flash("Staff account saved.", "success")
            return redirect(url_for("admin.staff_list"))
        return render_template("admin/staff_form.html", values=values, errors=errors, editing=True, roles=site_data.ROLES), 422
    return render_template("admin/staff_form.html", values=values, errors=errors, editing=True, roles=site_data.ROLES)


@admin_bp.post("/staff/<int:uid>/reset")
@admin_only
def staff_reset(uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    pw = request.form.get("password") or ""
    if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        flash("Password not changed: use at least 10 characters with upper and lower case letters and a number.", "danger")
    else:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), uid))
        audit("staff password reset", user["username"], commit=False)
        conn.commit()
        flash(f"New password set for {user['username']}.", "success")
    return redirect(url_for("admin.staff_list"))


# ---------------------------------------------------------------------------
# Reports, activity log, backup
# ---------------------------------------------------------------------------
@admin_bp.get("/reports")
@security.login_required
def reports():
    conn = get_db()
    marks = ",".join("?" * len(site_data.SEAT_STATUSES))
    status_counts = {s: 0 for s in site_data.STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) n FROM admissions GROUP BY status"):
        status_counts[r["status"]] = r["n"]
    per_course = conn.execute(
        f"""SELECT c.code, c.name, c.seats, COUNT(a.id) applied, ROUND(AVG(a.percentage), 1) avg_pct,
                   SUM(CASE WHEN a.status IN ({marks}) THEN 1 ELSE 0 END) filled
            FROM courses c LEFT JOIN admissions a ON a.course_code = c.code
            GROUP BY c.id ORDER BY c.sort_order""", site_data.SEAT_STATUSES).fetchall()

    today = site_data.today_ist()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    by_day = {r["d"]: r["n"] for r in conn.execute(
        "SELECT date(created_at, '+330 minutes') d, COUNT(*) n FROM admissions GROUP BY d")}
    series = [(d, by_day.get(d.isoformat(), 0)) for d in days]
    peak = max([n for _, n in series] + [1])
    bars = [{"x": 10 + i * 20, "h": round(n / peak * 110), "n": n, "label": d.strftime("%d %b")}
            for i, (d, n) in enumerate(series)]
    for b in bars:
        b["y"] = 130 - b["h"]

    def breakdown(column, limit=8):
        return conn.execute(f"SELECT COALESCE({column}, 'Not stated') k, COUNT(*) n FROM admissions GROUP BY k ORDER BY n DESC LIMIT {limit}").fetchall()

    return render_template(
        "admin/reports.html", status_counts=status_counts, per_course=per_course, bars=bars, peak=peak,
        total=sum(status_counts.values()), states=breakdown("state"), genders=breakdown("gender"),
        categories=breakdown("category"), quals=breakdown("qualification"),
        students=conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        docs=conn.execute("SELECT status, COUNT(*) n FROM documents GROUP BY status").fetchall())


@admin_bp.get("/activity")
@admin_only
def activity():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    per = 50
    pages = max(1, -(-total // per))
    try:
        page = min(max(1, int(request.args.get("page", 1))), pages)
    except ValueError:
        page = 1
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?", (per, (page - 1) * per)).fetchall()
    return render_template("admin/activity.html", rows=rows, page=page, pages=pages, total=total)


@admin_bp.post("/backup")
@admin_only
def backup():
    """Download a consistent copy of the whole database (applications, documents, accounts)."""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "backup.db")
        dest = sqlite3.connect(path)
        get_db().backup(dest)
        dest.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
        dest.close()
        with open(path, "rb") as fh:
            data = fh.read()
    audit("backup download", f"{len(data) // 1024} KB")
    name = f"miutm-backup-{site_data.today_ist().isoformat()}.db"
    return send_file(io.BytesIO(data), mimetype="application/octet-stream", as_attachment=True, download_name=name)


# ---------------------------------------------------------------------------
# Site settings: admission dates and contact details, editable without touching code
# ---------------------------------------------------------------------------
@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_only
def settings_page():
    errors = {}
    values = site_settings.current_values()
    if request.method == "POST":
        values, errors = site_settings.parse(request.form)
        if not errors:
            site_settings.save(get_db(), values)
            audit("settings changed", "site settings", f"session {values['session']}")
            flash("Settings saved. They are live on the website now.", "success")
            return redirect(url_for("admin.settings_page"))
        return render_template("admin/settings.html", values=values, errors=errors, date_keys=site_settings.DATE_KEYS, state=site_data.admissions_state()), 422
    return render_template("admin/settings.html", values=values, errors=errors, date_keys=site_settings.DATE_KEYS, state=site_data.admissions_state())
