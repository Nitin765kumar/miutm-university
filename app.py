"""
MIUTM portal - version 2

Run locally:   flask --app app run --debug
Run on Render: gunicorn app:app   (see render.yaml)
"""
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta

import click
from flask import (Flask, abort, flash, make_response, redirect, render_template, request,
                   session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

import admin_more  # noqa: F401  (adds the rest of the /admin routes)
import apply_flow
import settings as site_settings
import db as dbm
import mailer
import security
import site_data
import validators
from admin import admin_bp
from student import student_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------
def inr(value):
    """95000 -> ₹95,000 ; 185000 -> ₹1,85,000 (Indian digit grouping)."""
    n = int(value)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return "\u20b9" + ("-" if n < 0 else "") + s


def _parse(value):
    if hasattr(value, "year"):
        return value
    value = str(value)
    fmt = "%Y-%m-%d %H:%M:%S" if len(value) > 10 else "%Y-%m-%d"
    return datetime.strptime(value[:19], fmt)


def dmy(value):
    """'2026-10-12' -> '12 Oct 2026'"""
    if not value:
        return ""
    d = _parse(value)
    return f"{d.day} {d:%b %Y}"


def mon_year(value):
    """'2026-11-07' -> 'Nov 2026'"""
    d = _parse(value)
    return f"{d:%b %Y}"


def ist(value):
    """Stored UTC timestamp -> '12 Oct 2026, 3:42 pm' in Indian time."""
    if not value:
        return ""
    d = _parse(value) + timedelta(hours=5, minutes=30)
    return f"{d.day} {d:%b %Y}, {d.strftime('%I:%M %p').lstrip('0').lower()}"


def slugify_status(value):
    return (value or "").lower().replace(" ", "-")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def _load_secret_key(instance_path):
    """Use SECRET_KEY from the environment; otherwise create one once and keep it on disk."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    os.makedirs(instance_path, exist_ok=True)
    path = os.path.join(instance_path, "secret_key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    with open(path) as fh:
        return fh.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_path=os.path.join(BASE_DIR, "instance"))
    on_render = bool(os.environ.get("RENDER"))

    app.config.update(
        SECRET_KEY=_load_secret_key(app.instance_path),
        DATABASE=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "miutm.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=site_data.env_flag("SESSION_COOKIE_SECURE", on_render),
        PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.environ.get("SESSION_DAYS", "90"))),
        MAX_CONTENT_LENGTH=14 * 1024 * 1024,  # room for 6 files of 2 MB; non-upload forms are held to 64 KB below
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USER=os.environ.get("SMTP_USER", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", "MIUTM <no-reply@miutm.example>"),
        SMTP_TLS=site_data.env_flag("SMTP_TLS", True),
        SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=30),
        RATELIMIT_DISABLED=False,
    )
    if test_config:
        app.config.update(test_config)

    # Render (and most hosts) sit behind a proxy that terminates HTTPS.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO)
    if not os.environ.get("SECRET_KEY"):
        app.logger.warning("SECRET_KEY is not set; using a key stored in instance/secret_key.")

    dbm.init_db(app)
    app.teardown_appcontext(dbm.close_db)

    app.jinja_env.filters.update(inr=inr, dmy=dmy, ist=ist, mon_year=mon_year, status_slug=slugify_status)
    # A global (not a context variable) so imported macros can call it too.
    app.jinja_env.globals["csrf_token"] = security.csrf_token
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    @app.template_global()
    def asset(path):
        """Static file URL with a version number so browsers pick up changes."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, path)))
        except OSError:
            version = 0
        return url_for("static", filename=path, v=version)

    @app.context_processor
    def inject_globals():
        return dict(
            site=site_data.current_site(),
            departments=site_data.DEPARTMENTS,
            demo_mode=site_data.DEMO_MODE,
            allow_indexing=site_data.ALLOW_INDEXING,
            adm_state=site_data.admissions_state(),
            cycle=site_data.current_cycle(),
            developer_links=site_data.DEVELOPER_LINKS,
            current_year=site_data.today_ist().year,
            endpoint=request.endpoint or "",
            current_student=security.current_student(),
            staff_user=security.current_staff(),
            email_on=mailer.email_enabled(),
        )

    app.before_request(security.verify_csrf)

    UPLOAD_ENDPOINTS = {"apply_documents", "student.upload_document"}

    @app.before_request
    def small_forms_only():
        """Only the document pages may receive big requests."""
        if request.method == "POST" and (request.content_length or 0) > 64 * 1024 and request.endpoint not in UPLOAD_ENDPOINTS:
            abort(413)

    @app.before_request
    def load_settings():
        if request.endpoint != "static":
            site_settings.apply(dbm.get_db())

    app.after_request(security.add_security_headers)

    register_public_routes(app)
    apply_flow.register(app)
    app.register_blueprint(admin_bp)
    app.register_blueprint(student_bp)
    register_errors(app)
    register_cli(app)
    return app


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------
def register_public_routes(app):
    from db import get_db

    def all_courses():
        return get_db().execute("SELECT * FROM courses WHERE is_published = 1 ORDER BY sort_order, id").fetchall()

    @app.get("/")
    def index():
        conn = get_db()
        courses = all_courses()
        notices = conn.execute(
            "SELECT * FROM notices WHERE is_published = 1 ORDER BY published_on DESC, id DESC LIMIT 3"
        ).fetchall()
        stats = {
            "programmes": len(courses),
            "schools": len({c["school"] for c in courses}),
            "seats": sum(c["seats"] for c in courses),
        }
        schools = {}
        for c in courses:
            schools.setdefault(c["school"], []).append(c)
        return render_template("index.html", courses=courses, notices=notices, stats=stats,
                               schools=schools, timeline=site_data.timeline())

    @app.get("/about")
    def about():
        conn = get_db()
        courses = all_courses()
        faculty = conn.execute("SELECT * FROM faculty WHERE is_published = 1 ORDER BY id").fetchall()
        schools = {}
        for c in courses:
            schools.setdefault(c["school"], []).append(c)
        stats = {"programmes": len(courses), "schools": len(schools),
                 "seats": sum(c["seats"] for c in courses)}
        levels = {}
        for lv in ("Certificate", "Diploma", "Undergraduate", "Postgraduate"):
            items = [c for c in courses if c["level"] == lv]
            if items:
                levels[lv] = items
        return render_template("about.html", faculty=faculty, team=site_data.TEAM, schools=schools,
                               stats=stats, levels=levels, about=site_data)

    @app.get("/programmes")
    def programmes():
        courses = all_courses()
        levels = []
        for c in courses:
            if c["level"] not in levels:
                levels.append(c["level"])
        return render_template("programmes.html", courses=courses, levels=levels)

    @app.get("/programmes/<slug>")
    def programme_detail(slug):
        conn = get_db()
        course = conn.execute("SELECT * FROM courses WHERE slug = ? AND is_published = 1", (slug,)).fetchone()
        if course is None:
            abort(404)
        related = conn.execute(
            "SELECT * FROM courses WHERE school = ? AND id != ? AND is_published = 1 ORDER BY sort_order",
            (course["school"], course["id"]),
        ).fetchall()
        return render_template("programme_detail.html", course=course, related=related,
                               topics=[t.strip() for t in course["topics"].split(",")])

    # Old links from version 1
    @app.get("/courses")
    def old_courses():
        return redirect(url_for("programmes"), 301)

    @app.get("/track-admission")
    def old_track():
        return redirect(url_for("track"), 301)

    @app.get("/admissions")
    def old_admissions():
        return redirect(url_for("admin.applications"), 301)

    # ---- Admissions -------------------------------------------------------
    @app.get("/admission")
    def admission():
        faqs = get_db().execute("SELECT * FROM faqs WHERE is_published = 1 ORDER BY sort_order, id").fetchall()
        return render_template("admission.html", timeline=site_data.timeline(), courses=all_courses(), faqs=faqs)

    @app.route("/track", methods=["GET", "POST"])
    def track():
        record, events, error = None, [], None
        if request.method == "POST":
            if security.too_many("track", security.client_ip(), 12, 600):
                abort(429)
            number = (request.form.get("application_no") or "").strip().upper()
            dob = (request.form.get("dob") or "").strip()
            conn = get_db()
            record = conn.execute(
                "SELECT * FROM admissions WHERE application_no = ? AND dob = ?", (number, dob)
            ).fetchone()
            if record is None:
                error = ("We could not find an application with that number and date of birth. "
                         "Check both and try again.")
            else:
                events = conn.execute(
                    "SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id", (record["id"],)
                ).fetchall()
        return render_template("track.html", record=record, events=events, error=error,
                               status_help=site_data.STATUS_HELP,
                               form={"application_no": request.form.get("application_no", "")})

    # ---- Contact ------------------------------------------------------------
    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        values, errors = {}, {}
        if request.method == "POST":
            if security.too_many("contact", security.client_ip(), 5, 3600):
                abort(429)
            if request.form.get("website"):
                return redirect(url_for("contact"))
            values, errors = validators.validate_contact(request.form)
            if not errors:
                conn = get_db()
                conn.execute(
                    """INSERT INTO contact_messages (name, email, phone, department, subject, message)
                       VALUES (?,?,?,?,?,?)""",
                    (values["name"], values["email"], values["phone"] or None, values["department"],
                     values["subject"], values["message"]),
                )
                conn.commit()
                flash("Thanks. Your message has been sent. We reply within 2 working days.", "success")
                return redirect(url_for("contact"))
            return render_template("contact.html", values=values, errors=errors), 422
        return render_template("contact.html", values=values, errors=errors)

    # ---- News, scholarships, support, search -------------------------------
    @app.get("/news")
    def news():
        conn = get_db()
        today = site_data.today_ist().isoformat()
        notices = conn.execute("SELECT * FROM notices WHERE is_published = 1 ORDER BY published_on DESC, id DESC").fetchall()
        upcoming = conn.execute(
            "SELECT * FROM events WHERE is_published = 1 AND COALESCE(ends_on, starts_on) >= ? ORDER BY starts_on", (today,)).fetchall()
        past = conn.execute(
            "SELECT * FROM events WHERE is_published = 1 AND COALESCE(ends_on, starts_on) < ? ORDER BY starts_on DESC LIMIT 6", (today,)).fetchall()
        return render_template("news.html", notices=notices, upcoming=upcoming, past=past)

    @app.get("/scholarships")
    def scholarships():
        return render_template("scholarships.html", items=site_data.SCHOLARSHIPS)

    @app.route("/support", methods=["GET", "POST"])
    def support():
        values, errors = {}, {}
        me = security.current_student()
        if request.method == "GET" and me:
            values = {"name": me["full_name"], "email": me["email"], "phone": me["phone"] or ""}
        if request.method == "POST":
            if security.too_many("ticket", security.client_ip(), 5, 3600):
                abort(429)
            if request.form.get("website"):
                return redirect(url_for("support"))
            values, errors = validators.validate_ticket(request.form)
            if not errors:
                conn = get_db()
                ticket_no = None
                for _ in range(12):
                    candidate = f"TKT-{site_data.today_ist().year}-{secrets.randbelow(900000) + 100000}"
                    try:
                        conn.execute(
                            """INSERT INTO tickets (ticket_no, name, email, phone, category, subject, message)
                               VALUES (?,?,?,?,?,?,?)""",
                            (candidate, values["name"], values["email"], values["phone"] or None,
                             values["category"], values["subject"], values["message"]))
                        conn.commit()
                        ticket_no = candidate
                        break
                    except sqlite3.IntegrityError:
                        conn.rollback()
                if ticket_no is None:
                    abort(500)
                mailer.ticket_received({"name": values["name"], "email": values["email"], "ticket_no": ticket_no,
                                        "subject": values["subject"]})
                session["last_ticket"] = ticket_no
                return redirect(url_for("support_done"))
            return render_template("support.html", values=values, errors=errors,
                                   categories=site_data.TICKET_CATEGORIES), 422
        return render_template("support.html", values=values, errors=errors, categories=site_data.TICKET_CATEGORIES)

    @app.get("/support/done")
    def support_done():
        number = session.get("last_ticket")
        if not number:
            return redirect(url_for("support"))
        return render_template("support_done.html", number=number)

    @app.route("/support/track", methods=["GET", "POST"])
    def support_track():
        ticket, error = None, None
        if request.method == "POST":
            if security.too_many("ticket-track", security.client_ip(), 12, 600):
                abort(429)
            number = (request.form.get("ticket_no") or "").strip().upper()
            email = (request.form.get("email") or "").strip().lower()
            ticket = get_db().execute("SELECT * FROM tickets WHERE ticket_no = ? AND email = ?", (number, email)).fetchone()
            if ticket is None:
                error = "We could not find a ticket with that number and email."
        return render_template("support_track.html", ticket=ticket, error=error,
                               form={"ticket_no": request.form.get("ticket_no", "")})

    @app.get("/search")
    def search():
        q = (request.args.get("q") or "").strip()[:60]
        results = {}
        if len(q) >= 2:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conn = get_db()
            results["programmes"] = conn.execute(
                """SELECT * FROM courses WHERE is_published = 1 AND (name LIKE ? ESCAPE '\\' OR topics LIKE ? ESCAPE '\\'
                   OR school LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR code LIKE ? ESCAPE '\\') ORDER BY sort_order""",
                (like,) * 5).fetchall()
            results["notices"] = conn.execute(
                "SELECT * FROM notices WHERE is_published = 1 AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') ORDER BY published_on DESC",
                (like,) * 2).fetchall()
            results["events"] = conn.execute(
                "SELECT * FROM events WHERE is_published = 1 AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\') ORDER BY starts_on DESC",
                (like,) * 2).fetchall()
            results["faqs"] = conn.execute(
                "SELECT * FROM faqs WHERE is_published = 1 AND (question LIKE ? ESCAPE '\\' OR answer LIKE ? ESCAPE '\\') ORDER BY sort_order",
                (like,) * 2).fetchall()
        count = sum(len(v) for v in results.values())
        return render_template("search.html", q=q, results=results, count=count)

    @app.post("/logout")
    def logout_all():
        """The header button: signs out of every account in this browser (student and staff)."""
        security.sign_out_all()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.get("/login")
    def login_shortcut():
        return redirect(url_for("student.login"))

    @app.get("/signup")
    def signup_shortcut():
        return redirect(url_for("student.register"))

    # ---- Legal --------------------------------------------------------------
    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.get("/terms")
    def terms():
        return render_template("terms.html")

    @app.get("/accessibility")
    def accessibility():
        return render_template("accessibility.html")

    # ---- Machine-readable ---------------------------------------------------
    @app.get("/robots.txt")
    def robots():
        if site_data.ALLOW_INDEXING:
            body = (f"User-agent: *\nDisallow: /admin\nDisallow: /student\nDisallow: /track\nDisallow: /support/track\nDisallow: /admission/apply\n"
                    f"Sitemap: {request.url_root}sitemap.xml\n")
        else:
            body = "User-agent: *\nDisallow: /\n"
        resp = make_response(body)
        resp.mimetype = "text/plain"
        return resp

    @app.get("/sitemap.xml")
    def sitemap():
        pages = [url_for(e, _external=True) for e in
                 ("index", "about", "programmes", "admission", "news", "scholarships", "support", "contact", "privacy", "terms", "accessibility")]
        pages += [url_for("programme_detail", slug=c["slug"], _external=True) for c in all_courses()]
        xml = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        xml += [f"<url><loc>{p}</loc></url>" for p in pages]
        xml.append("</urlset>")
        resp = make_response("\n".join(xml))
        resp.mimetype = "application/xml"
        return resp

    @app.get("/healthz")
    def healthz():
        get_db().execute("SELECT 1").fetchone()
        return "ok", 200, {"Content-Type": "text/plain", "Cache-Control": "no-store"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def register_errors(app):
    messages = {
        400: ("Request not accepted",
              "Your session expired or the form was out of date. Go back, reload the page and try again."),
        403: ("Not allowed", "You do not have access to this page."),
        404: ("Page not found", "The page you asked for does not exist or has moved."),
        405: ("Not allowed", "That action is not available on this page."),
        413: ("Too much data", "The form you sent was larger than allowed."),
        429: ("Too many attempts", "You have tried this a few times in a short while. Wait a few minutes, then try again."),
        500: ("Something went wrong", "The server hit a problem. It has been logged. Please try again in a moment."),
    }

    def render(code):
        title, text = messages.get(code, ("Error", "Something went wrong."))
        return render_template("error.html", code=code, title=title, text=text), code

    for code in messages:
        app.register_error_handler(code, lambda e, c=code: render(c))

    @app.errorhandler(Exception)
    def unhandled(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e.get_response()
        app.logger.exception("Unhandled error")
        return render(500)


# ---------------------------------------------------------------------------
# Command line helpers:  flask --app app create-admin
# ---------------------------------------------------------------------------
def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.password_option()
    def create_admin(username, password):
        """Create an administrator, or reset the password of an existing account (and make it an
        active administrator). Use this if you lose the staff password."""
        username = username.strip().lower()
        conn = sqlite3.connect(app.config["DATABASE"])
        h = generate_password_hash(password)
        cur = conn.execute("UPDATE users SET password_hash = ?, role = 'admin', is_active = 1 WHERE lower(username) = ?",
                           (h, username))
        if cur.rowcount == 0:
            conn.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, 'Administrator', 'admin')",
                         (username, h))
            click.echo(f"Created administrator '{username}'. Sign in at /admin.")
        else:
            click.echo(f"Password reset for '{username}', which is now an active administrator. Sign in at /admin.")
        conn.commit()
        conn.close()

    @app.cli.command("list-staff")
    def list_staff():
        """Show the staff accounts that exist in this database."""
        conn = sqlite3.connect(app.config["DATABASE"])
        rows = conn.execute("SELECT username, role, is_active FROM users ORDER BY id").fetchall()
        conn.close()
        click.echo(f"Database: {app.config['DATABASE']}")
        for username, role, active in rows:
            click.echo(f"  {username:20} {role:9} {'active' if active else 'DISABLED'}")
        if not rows:
            click.echo("  (no staff accounts)")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
