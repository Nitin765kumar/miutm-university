"""
security.py - the small set of protections every request passes through.

* CSRF tokens on every POST (no extra package needed)
* a simple in-memory rate limiter for forms and login
* login_required for the admin area
* security headers, including a Content-Security-Policy

Note on the rate limiter: it lives in each worker's memory. That is fine for a single
small server (the default here). If you scale to many workers or servers, move it to
Redis or use a package such as Flask-Limiter.
"""
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from db import get_db


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def verify_csrf():
    """Call in before_request. Aborts with 400 if a POST has no valid token."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="csrf")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_hits = defaultdict(deque)
_lock = threading.Lock()


def too_many(bucket, key, limit, window_seconds):
    """
    Record a hit and return True if `key` has made more than `limit` hits in the window.
    Use one bucket name per feature, e.g. too_many("login", ip, 8, 900).
    """
    if current_app.config.get("RATELIMIT_DISABLED"):
        return False
    now = time.monotonic()
    k = (bucket, key)
    with _lock:
        q = _hits[k]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        # occasional cleanup so the dict cannot grow forever
        if len(_hits) > 5000:
            for stale in [kk for kk, qq in _hits.items() if not qq or now - qq[-1] > 3600]:
                _hits.pop(stale, None)
    return False


def reset_rate_limits():
    with _lock:
        _hits.clear()


def client_ip():
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Sign-in guards
# ---------------------------------------------------------------------------
STAFF_KEYS = ("admin_id", "admin_name", "admin_role")
STUDENT_KEYS = ("student_id", "student_email")


def remember_destination():
    """After sign-in, come back to the page that asked for it."""
    if request.method == "GET":
        session["next"] = request.full_path.rstrip("?")


_remember_destination = remember_destination  # old name


def _finish_login(remember):
    session.pop("_csrf", None)  # fresh CSRF token after signing in
    # "Keep me signed in" lasts SESSION_DAYS days from the last visit; otherwise until the browser closes.
    session.permanent = bool(remember)


def sign_in_staff(user, remember=True):
    """Staff and student sign-in are independent: signing in as one never signs out the other."""
    for key in STAFF_KEYS:
        session.pop(key, None)
    session["admin_id"], session["admin_name"], session["admin_role"] = user["id"], user["username"], user["role"]
    g.__dict__.pop("staff", None)
    _finish_login(remember)


def sign_in_student(student, remember=True):
    for key in STUDENT_KEYS:
        session.pop(key, None)
    session["student_id"], session["student_email"] = student["id"], student["email"]
    g.__dict__.pop("student", None)
    _finish_login(remember)


def sign_out_staff():
    for key in STAFF_KEYS:
        session.pop(key, None)
    g.__dict__.pop("staff", None)
    session.pop("_csrf", None)


def sign_out_student():
    for key in STUDENT_KEYS + ("last_app",):
        session.pop(key, None)
    g.__dict__.pop("student", None)
    session.pop("_csrf", None)


def sign_out_all():
    sign_out_staff()
    sign_out_student()


def current_staff():
    """The signed-in staff user (checked against the database on every request) or None."""
    if "staff" in g.__dict__:
        return g.staff
    g.staff = None
    uid = session.get("admin_id")
    if uid:
        row = get_db().execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)).fetchone()
        if row is None:  # removed or deactivated while signed in
            for key in ("admin_id", "admin_name", "admin_role"):
                session.pop(key, None)
        else:
            g.staff = row
    return g.staff


def current_student():
    if "student" in g.__dict__:
        return g.student
    g.student = None
    sid = session.get("student_id")
    if sid:
        row = get_db().execute("SELECT * FROM students WHERE id = ? AND is_active = 1", (sid,)).fetchone()
        if row is None:
            session.pop("student_id", None)
            session.pop("student_email", None)
        else:
            g.student = row
    return g.student


def login_required(view):
    """Staff only (any role)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_staff() is None:
            _remember_destination()
            flash("Sign in to continue.", "info")
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    """Staff with one of the given roles. Others get a 403 page."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_staff()["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_student() is None:
            _remember_destination()
            flash("Log in to continue.", "info")
            return redirect(url_for("student.login"))
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
CSP = "; ".join([
    "default-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "script-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def add_security_headers(response):
    h = response.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if request.is_secure and not current_app.debug:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Pages with personal data must never sit in a shared or browser cache.
    if request.path.startswith(("/admin", "/student", "/track", "/support/track", "/admission/success", "/admission/apply")):
        h["Cache-Control"] = "no-store"
    return response
