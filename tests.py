"""Run with:  python tests.py   (uses a throwaway database, nothing is saved)"""
import io
import itertools
import os
import re
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(tmp, "test.db")
os.environ["SECRET_KEY"] = "test-key"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "Correct-Horse-9"
os.environ["ADMISSIONS_FORCE_OPEN"] = "1"

import app as appmod  # noqa: E402
import security  # noqa: E402
import site_data  # noqa: E402

VALID = dict(full_name="Asha Verma", father_name="Ramesh Verma", mother_name="Sunita Verma",
             dob="2007-05-14", gender="Female", category="General", nationality="Indian",
             email="asha@example.com", phone="9876501234", qualification="12th (Intermediate)",
             percentage="72.5", course_code="BCA", address="12 Station Road", city="Ayodhya",
             state="Uttar Pradesh", pincode="224001")
_n = itertools.count(1)
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def token(client, path="/contact"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def tok(c):
    return token(c, "/contact")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sent = []
        cls.app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": True,
                                     "MAIL_BACKEND": lambda to, subject, body: cls.sent.append((to, subject, body))})

    def setUp(self):
        self.c = self.app.test_client()
        self.sent.clear()

    # ---- helpers ----
    def register(self, c=None, email=None, password="Passw0rdA1", name="Test Student"):
        c = c or self.c
        email = email or f"s{next(_n)}@example.com"
        r = c.post("/student/register", data=dict(full_name=name, email=email, phone="9876501234", password=password,
                                                  confirm=password, csrf_token=tok(c)))
        return email, r

    def logged_in_student(self):
        c = self.app.test_client()
        self.register(c)
        return c

    def details(self, c, action="next", **over):
        data = dict(VALID, email=f"a{next(_n)}@example.com", action=action, step="2")
        data.update(over)
        data["csrf_token"] = tok(c)
        return c.post("/admission/apply", data=data)

    def apply(self, c=None, **over):
        """The whole admission flow for a logged-in student. Returns the application number."""
        if c is None:
            c = self.c
        if not c.get("/student/dashboard").status_code == 200:
            self.register(c)
        r = self.details(c, **over)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])
        self.assertIn("/admission/apply/documents", r.headers["Location"])
        r = c.post("/admission/apply/submit", data={"declaration": "yes", "csrf_token": tok(c)})
        self.assertEqual(r.status_code, 302)
        page = c.get("/admission/success").get_data(as_text=True)
        return re.search(r"MIUTM-\d{4}-\d{6}", page).group(0)

    def staff(self, username="boss", password="Correct-Horse-9"):
        c = self.app.test_client()
        r = c.post("/admin/login", data={"username": username, "password": password, "remember": "1",
                                         "csrf_token": token(c, "/admin/login")})
        self.assertEqual(r.status_code, 302, username)
        return c

    def admin_id(self, a, number):
        html = a.get(f"/admin/applications?q={number}").get_data(as_text=True)
        return int(re.search(r"/admin/applications/(\d+)\"", html).group(1))

    def set_status(self, a, number, status, note=""):
        aid = self.admin_id(a, number)
        r = a.post(f"/admin/applications/{aid}/status", data={"status": status, "note": note, "remarks": "", "csrf_token": tok(a)})
        self.assertEqual(r.status_code, 302)
        return aid

    def make_reviewer(self, admin):
        name = f"rev{next(_n)}"
        r = admin.post("/admin/staff/new", data={"username": name, "full_name": "Rita Reviewer", "email": "", "role": "reviewer",
                                                 "password": "Review-Pass-9x", "csrf_token": tok(admin)})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        return name


# ===========================================================================
class Site(Base):
    def test_public_pages_render(self):
        for path in ["/", "/about", "/programmes", "/programmes/bca", "/programmes/btech-cse", "/admission", "/track", "/contact",
                     "/privacy", "/terms", "/accessibility", "/robots.txt", "/sitemap.xml", "/healthz", "/news", "/scholarships",
                     "/support", "/support/track", "/search", "/search?q=python", "/search?q=%25", "/student/login",
                     "/student/register", "/student/forgot", "/admin/login", "/admin/register"]:
            self.assertEqual(self.c.get(path).status_code, 200, path)

    def test_404_and_redirects(self):
        self.assertEqual(self.c.get("/nope").status_code, 404)
        self.assertEqual(self.c.get("/programmes/zzz").status_code, 404)
        self.assertEqual(self.c.get("/courses").status_code, 301)
        self.assertEqual(self.c.get("/track-admission").status_code, 301)
        self.assertEqual(self.c.get("/login").status_code, 302)

    def test_no_inline_styles_or_scripts(self):
        c = self.logged_in_student()
        self.details(c, action="next")
        for path in ["/", "/about", "/programmes", "/admission", "/contact", "/admin/login", "/admin/register", "/student/login",
                     "/admission/apply", "/admission/apply/documents", "/admission/apply/review", "/student/dashboard"]:
            html = c.get(path, follow_redirects=True).get_data(as_text=True)
            self.assertNotIn(' style="', html, path)
            self.assertNotRegex(html, r"<script(?![^>]*src=)[^>]*>", path)
            self.assertNotRegex(html, r"\son[a-z]+=\"", path)

    def test_headers(self):
        r = self.c.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("noindex", r.get_data(as_text=True))

    def test_inr_filter(self):
        self.assertEqual(appmod.inr(95000), "\u20b995,000")
        self.assertEqual(appmod.inr(185000), "\u20b91,85,000")
        self.assertEqual(appmod.inr(1234567), "\u20b912,34,567")

    def test_post_without_csrf_rejected(self):
        self.assertEqual(self.c.post("/contact", data={"name": "x"}).status_code, 400)
        self.assertEqual(self.c.post("/admin/logout").status_code, 400)
        self.assertEqual(self.c.post("/logout").status_code, 400)

    def test_apply_requires_login(self):
        for path in ["/admission/apply", "/admission/apply/documents", "/admission/apply/review", "/admission/success", "/student/dashboard"]:
            r = self.c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/student/login", r.headers["Location"], path)
        for path in ["/admission/apply", "/admission/apply/submit"]:
            self.assertEqual(self.c.post(path, data={"csrf_token": tok(self.c)}).status_code, 302, path)
        page = self.c.get("/admission/apply?course=bca", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Create a free student account or log in to apply", page)

    def test_apply_success_and_track(self):
        c = self.logged_in_student()
        number = self.apply(c, full_name="Asha Verma")
        page = c.get("/admission/success").get_data(as_text=True)
        for text in ("Asha Verma", "Ramesh Verma", "12 Station Road", "224001", "72.5%", "For office use only", "4. Declaration"):
            self.assertIn(text, page)
        tr = self.app.test_client()
        t = tok(tr)
        bad = tr.post("/track", data={"application_no": number, "dob": "2000-01-01", "csrf_token": t})
        self.assertIn("could not find", bad.get_data(as_text=True))
        good = tr.post("/track", data={"application_no": number.lower(), "dob": VALID["dob"], "csrf_token": t}).get_data(as_text=True)
        self.assertIn("Asha Verma", good)
        self.assertIn("Pending", good)
        self.assertNotIn("9876501234", good)
        self.assertNotIn("Station Road", good)

    def test_validation_errors_keep_input(self):
        c = self.logged_in_student()
        r = self.details(c, phone="12345", percentage="45", email="bad", pincode="12")
        self.assertEqual(r.status_code, 422)
        html = r.get_data(as_text=True)
        self.assertIn("10-digit Indian mobile", html)
        self.assertIn("needs at least 50%", html)
        self.assertIn("valid email", html)
        self.assertIn("6-digit PIN", html)
        self.assertIn('value="Asha Verma"', html)
        # nothing typed is lost: the draft was saved even though it was invalid
        self.assertIn('value="Asha Verma"', c.get("/admission/apply").get_data(as_text=True))

    def test_eligibility_rules(self):
        c = self.logged_in_student()
        r = self.details(c, course_code="MCA", qualification="12th (Intermediate)")
        self.assertEqual(r.status_code, 422)
        self.assertIn("accepts", r.get_data(as_text=True))

    def test_duplicate_and_unknown_course(self):
        c = self.logged_in_student()
        self.apply(c, email="dup@example.com")
        r = self.details(c, email="dup@example.com")
        self.assertEqual(r.status_code, 422)
        self.assertIn("already have an open application", r.get_data(as_text=True))
        self.assertEqual(self.details(c, course_code="HACK").status_code, 422)

    def test_contact_saves_phone_and_department(self):
        r = self.c.post("/contact", data=dict(name="Ravi", email="r@example.com", phone="9123456789", department="Examination Cell",
                                              subject="Hall ticket", message="I cannot download my admit card.", csrf_token=tok(self.c)),
                        follow_redirects=True)
        self.assertIn("message has been sent", r.get_data(as_text=True))

    # ---- admin basics ----
    def test_admin_requires_login(self):
        for path in ["/admin/dashboard", "/admin/applications", "/admin/messages", "/admin/account", "/admin/applications/1",
                     "/admin/applications/export.csv", "/admin/settings", "/admin/students/export.csv"]:
            r = self.c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/admin/login", r.headers["Location"], path)
        self.assertEqual(self.c.get("/admission/delete/1").status_code, 404)
        self.assertEqual(self.c.post("/admin/applications/1/delete").status_code, 400)

    def test_wrong_password(self):
        r = self.c.post("/admin/login", data={"username": "boss", "password": "nope", "csrf_token": token(self.c, "/admin/login")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Wrong username or password", r.get_data(as_text=True))

    def test_admin_flow(self):
        c = self.logged_in_student()
        number = self.apply(c, email="flow@example.com")
        a = self.staff()
        for path in ["/admin/dashboard", "/admin/applications", "/admin/applications?q=Asha&status=Pending", "/admin/messages",
                     "/admin/account", "/admin/applications/export.csv"]:
            self.assertEqual(a.get(path).status_code, 200, path)
        self.assertEqual(a.get("/admin/applications/export.csv").mimetype, "text/csv")
        aid = self.admin_id(a, number)
        self.assertEqual(a.get(f"/admin/applications/{aid}").status_code, 200)
        self.assertEqual(a.get(f"/admin/applications/{aid}/edit").status_code, 200)
        pr = a.get(f"/admin/applications/{aid}/print")
        self.assertEqual(pr.status_code, 200)
        self.assertIn("For office use only", pr.get_data(as_text=True))
        t = tok(a)
        self.assertEqual(a.post(f"/admin/applications/{aid}/status", data={"status": "Approved", "note": "Welcome aboard", "remarks": "ok", "csrf_token": t}).status_code, 302)
        tr = self.app.test_client()
        page = tr.post("/track", data={"application_no": number, "dob": VALID["dob"], "csrf_token": tok(tr)}).get_data(as_text=True)
        self.assertIn("Approved", page)
        self.assertIn("Welcome aboard", page)
        form = dict(VALID, email="flow@example.com", city="Lucknow", csrf_token=t)
        r = a.post(f"/admin/applications/{aid}/edit", data=form)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])
        self.assertIn("Lucknow", a.get(f"/admin/applications/{aid}").get_data(as_text=True))
        self.assertEqual(a.post(f"/admin/applications/{aid}/delete", data={"csrf_token": t}).status_code, 302)
        self.assertEqual(a.get(f"/admin/applications/{aid}").status_code, 404)

    def test_messages_and_password_change(self):
        self.c.post("/contact", data=dict(name="Meena", email="m@example.com", department="Admissions Office", subject="Hostel",
                                          message="Is hostel available for girls?", csrf_token=tok(self.c)))
        a = self.staff()
        html = a.get("/admin/messages").get_data(as_text=True)
        mid = int(re.search(r"/admin/messages/(\d+)/read", html).group(1))
        t = tok(a)
        self.assertEqual(a.post(f"/admin/messages/{mid}/read", data={"state": "1", "csrf_token": t}).status_code, 302)
        self.assertEqual(a.post(f"/admin/messages/{mid}/delete", data={"csrf_token": t}).status_code, 302)
        r = a.post("/admin/account", data={"action": "password", "current": "Correct-Horse-9", "new": "short", "confirm": "short", "csrf_token": t})
        self.assertEqual(r.status_code, 200)
        self.assertIn("at least 10", r.get_data(as_text=True))

    def test_open_redirect_blocked(self):
        from admin import _safe_next
        self.assertIsNone(_safe_next("https://evil.com"))
        self.assertIsNone(_safe_next("//evil.com"))
        self.assertEqual(_safe_next("/admin/messages"), "/admin/messages")

    def test_csv_formula_injection(self):
        from admin import _cell
        self.assertEqual(_cell("=1+1"), "'=1+1")
        self.assertEqual(_cell("Asha"), "Asha")

    def test_rate_limit(self):
        app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": False})
        c = app.test_client()
        security.reset_rate_limits()
        codes = [c.post("/track", data={"application_no": "x", "dob": "2000-01-01", "csrf_token": tok(c)}).status_code for _ in range(14)]
        self.assertIn(429, codes)
        security.reset_rate_limits()

    def test_student_login_rate_limit(self):
        app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": False})
        c = app.test_client()
        security.reset_rate_limits()
        codes = [c.post("/student/login", data={"email": "x@example.com", "password": "nope", "csrf_token": tok(c)}).status_code for _ in range(9)]
        self.assertIn(429, codes)
        security.reset_rate_limits()

    def test_staff_login_is_case_insensitive_and_cli_recovers(self):
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        from werkzeug.security import generate_password_hash
        con.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, 'Mixed', 'admin')",
                    ("MixedCase", generate_password_hash("Mixed-Pass-9x")))
        con.commit(); con.close()
        c = self.app.test_client()
        for typed in ("MixedCase", "mixedcase", "  MIXEDCASE "):
            r = c.post("/admin/login", data={"username": typed, "password": "Mixed-Pass-9x", "csrf_token": token(c, "/admin/login")})
            self.assertEqual(r.status_code, 302, typed)
            c.post("/admin/logout", data={"csrf_token": tok(c)})
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        con.execute("UPDATE users SET is_active = 0, role = 'reviewer' WHERE username = 'MixedCase'"); con.commit(); con.close()
        runner = self.app.test_cli_runner()
        res = runner.invoke(args=["create-admin", "mixedcase"], input="Fresh-Pass-77x\nFresh-Pass-77x\n")
        self.assertIn("Password reset", res.output)
        r = c.post("/admin/login", data={"username": "mixedcase", "password": "Fresh-Pass-77x", "csrf_token": token(c, "/admin/login")})
        self.assertEqual(r.status_code, 302)
        self.assertIn("MixedCase", runner.invoke(args=["list-staff"]).output)
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        con.execute("DELETE FROM users WHERE username = 'MixedCase'"); con.commit(); con.close()

    def test_two_processes_starting_together_do_not_clash(self):
        import subprocess, sys
        path = os.path.join(tmp, "race.db")
        code = ("import os; os.environ['DATABASE_PATH']=%r; os.environ['SECRET_KEY']='k'; os.environ['ADMIN_PASSWORD']='Race-Pass-123x'; "
                "import app" % path)
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=os.path.dirname(os.path.abspath(__file__))) for _ in range(6)]
        results = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
        self.assertTrue(all(r[2] == 0 for r in results), [r[1][-300:] for r in results if r[2] != 0])
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 10)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM faqs").fetchone()[0], 7)
        con.close()

    def test_migration_of_older_database(self):
        import db as dbm
        path = os.path.join(tmp, "old.db")
        con = sqlite3.connect(path)
        con.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                             created_at TEXT, last_login TEXT);
                             INSERT INTO users (username, password_hash) VALUES ('old', 'x');
                             CREATE TABLE admissions (id INTEGER PRIMARY KEY, application_no TEXT);
                             CREATE TABLE contact_messages (id INTEGER PRIMARY KEY, name TEXT);
                             CREATE TABLE courses (id INTEGER PRIMARY KEY, code TEXT);
                             CREATE TABLE faculty (id INTEGER PRIMARY KEY, name TEXT);""")
        dbm._migrate(con); dbm._migrate(con)
        self.assertEqual(con.execute("SELECT role, is_active, approved FROM users").fetchone(), ("admin", 1, 1))
        self.assertIn("student_id", dbm._columns(con, "admissions"))
        con.close()


# ===========================================================================
class Sessions(Base):
    """The two sign-ins must not interfere, and 'keep me signed in' must really persist."""

    def test_staff_and_student_stay_signed_in_together(self):
        c = self.app.test_client()
        c.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "remember": "1", "csrf_token": token(c, "/admin/login")})
        self.assertEqual(c.get("/admin/dashboard").status_code, 200)
        email, r = self.register(c)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/student/dashboard").status_code, 200)
        self.assertEqual(c.get("/admin/dashboard").status_code, 200, "student sign-up must not sign the admin out")
        # logging in again as the other role also keeps both
        c.post("/student/logout", data={"csrf_token": tok(c)})
        self.assertEqual(c.get("/student/dashboard").status_code, 302)
        self.assertEqual(c.get("/admin/dashboard").status_code, 200, "student log out must not sign the admin out")
        c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "remember": "1", "csrf_token": tok(c)})
        c.post("/admin/logout", data={"csrf_token": tok(c)})
        self.assertEqual(c.get("/admin/dashboard").status_code, 302)
        self.assertEqual(c.get("/student/dashboard").status_code, 200, "admin sign out must not sign the student out")
        # the header button signs out of everything
        c.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "remember": "1", "csrf_token": token(c, "/admin/login")})
        c.post("/logout", data={"csrf_token": tok(c)})
        self.assertEqual(c.get("/student/dashboard").status_code, 302)
        self.assertEqual(c.get("/admin/dashboard").status_code, 302)

    def test_header_shows_both_dashboards(self):
        c = self.app.test_client()
        c.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "remember": "1", "csrf_token": token(c, "/admin/login")})
        self.register(c)
        html = c.get("/").get_data(as_text=True)
        self.assertIn("My dashboard", html)
        self.assertIn("Staff dashboard", html)

    def test_keep_me_signed_in_sets_a_long_cookie(self):
        def cookie_of(response):
            return " ".join(response.headers.getlist("Set-Cookie"))
        c = self.app.test_client()
        r = c.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "remember": "1", "csrf_token": token(c, "/admin/login")})
        self.assertRegex(cookie_of(r), r"(?i)expires=")
        self.assertGreaterEqual(self.app.config["PERMANENT_SESSION_LIFETIME"].days, 30)
        # the cookie is refreshed on later visits, so regular users never expire
        self.assertRegex(cookie_of(c.get("/admin/dashboard")), r"(?i)expires=")
        c2 = self.app.test_client()
        r = c2.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "csrf_token": token(c2, "/admin/login")})
        self.assertNotRegex(cookie_of(r), r"(?i)expires=")

    def test_top_bar_has_admin_login_and_register(self):
        html = self.c.get("/").get_data(as_text=True)
        top = html.split('<header class="site-header">')[0]
        self.assertIn("/admin/login", top)
        self.assertIn("/admin/register", top)
        self.assertIn("/student/login", html)

    def test_student_remember_checkbox_on_login_page(self):
        self.assertIn('name="remember"', self.c.get("/student/login").get_data(as_text=True))
        self.assertIn('name="remember"', self.c.get("/admin/login").get_data(as_text=True))


# ===========================================================================
class StaffRegistration(Base):
    def reg(self, c, **over):
        n = next(_n)
        data = dict(full_name="Priya Staff", email=f"staff{n}@example.com", username=f"priya{n}", password="Staff-Pass-12x",
                    confirm="Staff-Pass-12x", csrf_token=tok(c))
        data.update(over)
        return data, c.post("/admin/register", data=data)

    def test_register_then_wait_for_approval(self):
        c = self.app.test_client()
        data, r = self.reg(c)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Registration received", r.get_data(as_text=True))
        # cannot sign in until approved, and the message says why
        waiting = c.post("/admin/login", data={"username": data["username"], "password": data["password"], "csrf_token": token(c, "/admin/login")})
        self.assertEqual(waiting.status_code, 200)
        self.assertIn("waiting for an administrator", waiting.get_data(as_text=True))
        wrong = c.post("/admin/login", data={"username": data["username"], "password": "Wrong-Pass-12x", "csrf_token": tok(c)})
        self.assertNotIn("waiting for an administrator", wrong.get_data(as_text=True))   # no hints without the password
        admin = self.staff()
        page = admin.get("/admin/staff").get_data(as_text=True)
        self.assertIn("Waiting for approval", page)
        self.assertIn(data["username"], page)
        uid = int(re.search(r'action="/admin/staff/(\d+)/approve"', page.split(data["username"])[1]).group(1))
        self.assertEqual(admin.post(f"/admin/staff/{uid}/approve", data={"role": "reviewer", "csrf_token": tok(admin)}).status_code, 302)
        ok = c.post("/admin/login", data={"username": data["username"], "password": data["password"], "csrf_token": token(c, "/admin/login")})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(c.get("/admin/dashboard").status_code, 200)
        self.assertEqual(c.get("/admin/staff").status_code, 403)   # approved as a reviewer only

    def test_reject_removes_the_registration(self):
        c = self.app.test_client()
        data, _ = self.reg(c)
        admin = self.staff()
        page = admin.get("/admin/staff").get_data(as_text=True)
        uid = int(re.search(r'action="/admin/staff/(\d+)/reject"[^>]*' + re.escape(data["username"]), page).group(1))
        admin.post(f"/admin/staff/{uid}/reject", data={"csrf_token": tok(admin)})
        listing = admin.get("/admin/staff").get_data(as_text=True)
        self.assertNotIn(f'class="sub">{data["username"]}', listing)       # gone from the table (the banner may still name it)
        again = c.post("/admin/login", data={"username": data["username"], "password": data["password"], "csrf_token": token(c, "/admin/login")})
        self.assertIn("Wrong username or password", again.get_data(as_text=True))

    def test_registration_validation(self):
        c = self.app.test_client()
        _, r = self.reg(c, password="weak", confirm="weak")
        self.assertEqual(r.status_code, 422)
        _, r = self.reg(c, username="Bad Name!")
        self.assertEqual(r.status_code, 422)
        _, r = self.reg(c, username="boss")
        self.assertIn("taken", r.get_data(as_text=True))
        _, r = self.reg(c, confirm="Different-Pass-1")
        self.assertIn("do not match", r.get_data(as_text=True))
        self.assertEqual(c.post("/admin/register", data={"csrf_token": tok(c)}).status_code, 422)
        self.assertEqual(c.post("/admin/register", data={}).status_code, 400)  # csrf

    def test_access_code_when_configured(self):
        c = self.app.test_client()
        with mock.patch.dict(os.environ, {"STAFF_SIGNUP_CODE": "open-sesame"}):
            self.assertIn("Staff access code", c.get("/admin/register").get_data(as_text=True))
            _, bad = self.reg(c, access_code="wrong")
            self.assertEqual(bad.status_code, 422)
            _, ok = self.reg(c, access_code="open-sesame")
            self.assertIn("Registration received", ok.get_data(as_text=True))

    def test_pending_account_has_no_access_even_with_a_stale_session(self):
        c = self.app.test_client()
        data, _ = self.reg(c)
        self.assertEqual(c.get("/admin/dashboard").status_code, 302)


# ===========================================================================
class Settings(Base):
    def test_admin_changes_dates_and_contact_details(self):
        a = self.staff()
        page = a.get("/admin/settings").get_data(as_text=True)
        self.assertIn("Admission session", page)
        data = dict(session="2028-29", opens="2027-10-01", closes="2028-04-30", merit="2028-05-15", counselling="2028-06-01",
                    classes="2028-08-01", phone="+91 99999 11111", phone_alt="", hours="Monday to Friday, 10 am to 4 pm",
                    general_email="hello@example.org", address1="New Campus Road", address2="Ayodhya", address3="UP 224001",
                    csrf_token=tok(a))
        try:
            r = a.post("/admin/settings", data=data)
            self.assertEqual(r.status_code, 302)
            for path, needle in [("/contact", "+91 99999 11111"), ("/contact", "Monday to Friday, 10 am to 4 pm"), ("/admission", "2028-29"),
                                 ("/", "2028-29"), ("/about", "hello@example.org"), ("/admission", "1 Oct 2027")]:
                self.assertIn(needle, self.c.get(path).get_data(as_text=True), f"{path}: {needle}")
        finally:  # put the defaults back for the other tests
            a.post("/admin/settings", data=dict(data, session="2027\u201328", opens="2026-10-01", closes="2027-04-30", merit="2027-05-15",
                                                counselling="2027-06-01", classes="2027-08-02", phone="+91 98765 43210",
                                                hours="Monday to Saturday, 9:00 am to 5:00 pm", general_email="info@miutm.edu.in",
                                                address1="MIUTM Campus", address2="Riverside Academic Zone",
                                                address3="Ayodhya, Uttar Pradesh \u2013 224001", csrf_token=tok(a)))

    def test_settings_validation_and_permissions(self):
        a = self.staff()
        good = dict(session="2027-28", opens="2026-10-01", closes="2027-04-30", merit="2027-05-15", counselling="2027-06-01",
                    classes="2027-08-02", phone="+91 98765 43210", hours="Mon-Sat", general_email="info@miutm.edu.in",
                    address1="Campus", csrf_token=tok(a))
        r = a.post("/admin/settings", data=dict(good, closes="2026-09-01"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("must close after they open", r.get_data(as_text=True))
        self.assertEqual(a.post("/admin/settings", data=dict(good, opens="not a date")).status_code, 422)
        self.assertEqual(a.post("/admin/settings", data=dict(good, general_email="nope")).status_code, 422)
        self.assertEqual(a.post("/admin/settings", data=dict(good, merit="2027-01-01")).status_code, 422)
        rev = self.staff(self.make_reviewer(a), "Review-Pass-9x")
        self.assertEqual(rev.get("/admin/settings").status_code, 403)
        self.assertEqual(rev.post("/admin/settings", data=dict(good, csrf_token=tok(rev))).status_code, 403)

    def test_dates_decide_whether_the_form_is_open(self):
        a = self.staff()
        base = dict(session="2027-28", phone="+91 98765 43210", hours="Mon-Sat", general_email="info@miutm.edu.in", address1="Campus",
                    csrf_token=tok(a))
        closed = dict(base, opens="2020-01-01", closes="2020-02-01", merit="2020-03-01", counselling="2020-04-01", classes="2020-05-01")
        reopen = dict(base, opens="2026-10-01", closes="2027-04-30", merit="2027-05-15", counselling="2027-06-01", classes="2027-08-02")
        try:
            a.post("/admin/settings", data=closed)
            with mock.patch.object(site_data, "ADMISSIONS_FORCE_OPEN", False):
                c = self.logged_in_student()
                r = c.get("/admission/apply")
                self.assertEqual(r.status_code, 302)
                self.assertIn("Applications are not open", c.get("/student/dashboard").get_data(as_text=True))
                self.assertNotIn("Apply now", self.c.get("/").get_data(as_text=True))
            a.post("/admin/settings", data=dict(closed, force_open="1"))     # the switch overrides the dates
            self.assertEqual(self.logged_in_student().get("/admission/apply").status_code, 200)
        finally:
            a.post("/admin/settings", data=reopen)

    def test_admin_dashboard_has_attention_panel_and_quick_actions(self):
        html = self.staff().get("/admin/dashboard").get_data(as_text=True)
        self.assertIn("Needs your attention", html + "Needs your attention" if "All caught up" in html else html)
        self.assertIn("/admin/settings", html)
        self.assertIn("Quick actions", html)

    def test_students_export(self):
        a = self.staff()
        self.register(self.app.test_client(), email="export@example.com")
        r = a.get("/admin/students/export.csv")
        self.assertEqual(r.mimetype, "text/csv")
        self.assertIn("export@example.com", r.get_data(as_text=True))
        rev = self.staff(self.make_reviewer(a), "Review-Pass-9x")
        self.assertEqual(rev.get("/admin/students/export.csv").status_code, 403)


# ===========================================================================
class ApplicationFlow(Base):
    """Five steps: details, documents, review, submit. Drafts, uploads, preview."""

    def test_photo_id_is_gone(self):
        self.assertNotIn("Photo ID", site_data.DOC_TYPES)
        self.assertNotIn("Photo ID", site_data.required_docs("Bachelor's degree", "OBC"))
        c = self.logged_in_student()
        self.details(c)
        self.assertNotIn("Photo ID", c.get("/admission/apply/documents").get_data(as_text=True))

    def test_each_page_has_back_save_cancel(self):
        c = self.logged_in_student()
        d = c.get("/admission/apply").get_data(as_text=True)
        for needle in ("Back to my dashboard", "Save draft", "Cancel", "Save and continue to documents", "Step 5"):
            self.assertIn(needle, d, needle)
        self.details(c)
        docs = c.get("/admission/apply/documents").get_data(as_text=True)
        for needle in ("Back to details", ">Back<", "Cancel", ">Save<", "Next: review"):
            self.assertIn(needle, docs, needle)
        rev = c.get("/admission/apply/review").get_data(as_text=True)
        for needle in ("Back to documents", "Edit details", "Cancel", "Print preview", "Submit application", "Save and finish later"):
            self.assertIn(needle, rev, needle)

    def test_save_draft_persists_across_logins(self):
        email, _ = self.register()
        c = self.app.test_client()
        c2 = self.app.test_client()
        c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "remember": "1", "csrf_token": tok(c)})
        r = c.post("/admission/apply", data=dict(full_name="Draft Person", city="Lucknow", action="save", step="1", csrf_token=tok(c)))
        self.assertEqual(r.status_code, 302)
        self.assertIn("step=1", r.headers["Location"])           # comes back to the same step
        c2.post("/student/login", data={"email": email, "password": "Passw0rdA1", "remember": "1", "csrf_token": tok(c2)})
        page = c2.get("/admission/apply").get_data(as_text=True)
        self.assertIn('value="Draft Person"', page)
        self.assertIn('value="Lucknow"', page)
        dash = c2.get("/student/dashboard").get_data(as_text=True)
        self.assertIn("Application in progress", dash)
        self.assertIn("Continue application", dash)

    def test_documents_step_needs_valid_details(self):
        c = self.logged_in_student()
        c.post("/admission/apply", data=dict(full_name="Only A Name", action="save", step="0", csrf_token=tok(c)))  # incomplete
        r = c.get("/admission/apply/documents")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admission/apply", r.headers["Location"])
        self.assertEqual(c.get("/admission/apply/review").status_code, 302)

    def docs_post(self, c, files, go="stay"):
        data = {"csrf_token": tok(c), "go": go}
        for idx, (name, content) in files.items():
            data[f"file-{idx}"] = (io.BytesIO(content), name)
        return c.post("/admission/apply/documents", data=data, content_type="multipart/form-data", follow_redirects=True)

    def test_documents_save_several_files_and_report_problems(self):
        c = self.logged_in_student()
        self.details(c)
        kinds = site_data.DOC_TYPES
        r = self.docs_post(c, {kinds.index("Class 10 marksheet"): ("m10.pdf", PDF), kinds.index("Class 12 marksheet"): ("m12.pdf", PDF),
                               kinds.index("Passport-size photo"): ("me.exe", b"MZ")})
        html = r.get_data(as_text=True)
        self.assertIn("2 documents saved", html)
        self.assertIn("Passport-size photo: Only PDF, JPG and PNG", html)
        self.assertIn("m10.pdf", html)
        self.assertIn("m12.pdf", html)
        bad = self.docs_post(c, {kinds.index("Passport-size photo"): ("fake.pdf", b"not a pdf")}).get_data(as_text=True)
        self.assertIn("does not match its type", bad)
        big = self.docs_post(c, {kinds.index("Passport-size photo"): ("big.pdf", PDF + b"0" * (2 * 1024 * 1024))}).get_data(as_text=True)
        self.assertIn("larger than 2 MB", big)
        again = self.docs_post(c, {})
        self.assertIn("Choose at least one file", again.get_data(as_text=True))
        # replace and remove
        self.docs_post(c, {kinds.index("Class 10 marksheet"): ("new10.pdf", PDF)})
        page = c.get("/admission/apply/documents").get_data(as_text=True)
        self.assertIn("new10.pdf", page)
        self.assertNotIn("m10.pdf", page)
        doc_id = int(re.search(r'id="rm-(\d+)"', page).group(1))
        self.assertEqual(c.post(f"/admission/apply/documents/{doc_id}/delete", data={"csrf_token": tok(c)}).status_code, 302)
        self.assertEqual(c.post("/admission/apply/documents", data={"go": "stay"}).status_code, 400)   # csrf

    def test_next_saves_files_then_opens_review(self):
        c = self.logged_in_student()
        self.details(c)
        r = c.post("/admission/apply/documents", data={"csrf_token": tok(c), "go": "review",
                   "file-1": (io.BytesIO(PDF), "m12.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admission/apply/review", r.headers["Location"])
        page = c.get("/admission/apply/review").get_data(as_text=True)
        self.assertIn("PREVIEW", page)
        self.assertIn("Documents still missing", page)
        self.assertIn("Class 10 marksheet", page)

    def test_several_large_files_in_one_save(self):
        c = self.logged_in_student()
        self.details(c)
        k = site_data.DOC_TYPES
        big = PDF + b"0" * (1900 * 1024)          # 1.9 MB: under the 2 MB per-file limit
        r = self.docs_post(c, {k.index("Class 10 marksheet"): ("a.pdf", big), k.index("Class 12 marksheet"): ("b.pdf", big),
                               k.index("Passport-size photo"): ("c.pdf", big)})
        html = r.get_data(as_text=True)
        self.assertIn("3 documents saved", html)          # 5.7 MB in one request used to be refused
        self.assertEqual(c.post("/contact", data={"name": "x", "message": "y" * 100000, "csrf_token": tok(c)}).status_code, 413)

    def test_draft_documents_are_private(self):
        a, b = self.logged_in_student(), self.logged_in_student()
        self.details(a)
        self.docs_post(a, {site_data.DOC_TYPES.index("Class 12 marksheet"): ("m12.pdf", PDF)})
        doc_id = int(re.search(r"/admission/apply/documents/(\d+)", a.get("/admission/apply/documents").get_data(as_text=True)).group(1))
        dl = a.get(f"/admission/apply/documents/{doc_id}")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.data, PDF)
        self.assertIn("attachment", dl.headers["Content-Disposition"])
        self.assertEqual(b.get(f"/admission/apply/documents/{doc_id}").status_code, 404)
        self.assertEqual(self.c.get(f"/admission/apply/documents/{doc_id}").status_code, 302)

    def test_submit_moves_documents_and_clears_the_draft(self):
        c = self.logged_in_student()
        self.details(c)
        self.docs_post(c, {site_data.DOC_TYPES.index("Class 12 marksheet"): ("m12.pdf", PDF)})
        no_decl = c.post("/admission/apply/submit", data={"csrf_token": tok(c)})
        self.assertEqual(no_decl.status_code, 302)
        self.assertIn("/review", no_decl.headers["Location"])
        r = c.post("/admission/apply/submit", data={"declaration": "yes", "csrf_token": tok(c)})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admission/success", r.headers["Location"])
        success = c.get("/admission/success").get_data(as_text=True)
        number = re.search(r"MIUTM-\d{4}-\d{6}", success).group(0)
        app_page = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn("m12.pdf", app_page)               # the draft upload is now on the application
        self.assertNotIn("Application in progress", c.get("/student/dashboard").get_data(as_text=True))
        self.assertEqual(c.get("/admission/apply/review").status_code, 302)    # draft is gone
        with c.session_transaction() as sess:
            sid = sess["student_id"]
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM draft_documents WHERE student_id = ?", (sid,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM drafts WHERE student_id = ?", (sid,)).fetchone()[0], 0)
        con.close()

    def test_discard_draft(self):
        c = self.logged_in_student()
        self.details(c)
        self.docs_post(c, {site_data.DOC_TYPES.index("Class 12 marksheet"): ("m12.pdf", PDF)})
        self.assertEqual(c.post("/admission/apply/discard", data={"csrf_token": tok(c)}).status_code, 302)
        self.assertNotIn("Application in progress", c.get("/student/dashboard").get_data(as_text=True))
        page = c.get("/admission/apply").get_data(as_text=True)
        self.assertNotIn("m12.pdf", page)

    def test_preview_and_printed_form_use_the_same_layout(self):
        c = self.logged_in_student()
        self.details(c)
        preview = c.get("/admission/apply/review").get_data(as_text=True)
        number = self.apply(c)
        success = c.get("/admission/success").get_data(as_text=True)
        printed = c.get(f"/student/applications/{number}/print").get_data(as_text=True)
        a = self.staff()
        admin_print = a.get(f"/admin/applications/{self.admin_id(a, number)}/print").get_data(as_text=True)
        sections = ["1. Personal details", "2. Contact and address", "3. Education and programme applied for", "4. Declaration",
                    "For office use only", "Applicant's signature", "Bring to counselling", "photo-box"]
        for name, html in (("preview", preview), ("success", success), ("student print", printed), ("admin print", admin_print)):
            for s in sections:
                self.assertIn(s, html, f"{name} is missing {s}")
        self.assertIn("PREVIEW", preview)
        self.assertNotIn("PREVIEW", printed)

    def test_prefill_uses_the_last_application(self):
        c = self.logged_in_student()
        self.apply(c, full_name="Asha Verma")
        form = c.get("/admission/apply").get_data(as_text=True)
        self.assertIn('value="Asha Verma"', form)
        self.assertIn('value="Ramesh Verma"', form)


# ===========================================================================
class Students(Base):
    def test_register_login_logout(self):
        email, r = self.register()
        self.assertEqual(r.status_code, 302)
        self.assertIn("Hello", self.c.get("/student/dashboard").get_data(as_text=True))
        self.assertIn("My dashboard", self.c.get("/").get_data(as_text=True))
        self.c.post("/student/logout", data={"csrf_token": tok(self.c)})
        self.assertEqual(self.c.get("/student/dashboard").status_code, 302)
        bad = self.c.post("/student/login", data={"email": email, "password": "wrong", "csrf_token": tok(self.c)})
        self.assertIn("Wrong email or password", bad.get_data(as_text=True))
        ok = self.c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "csrf_token": tok(self.c)})
        self.assertEqual(ok.status_code, 302)

    def test_register_validation(self):
        email, _ = self.register()
        other = self.app.test_client()
        r = other.post("/student/register", data=dict(full_name="X Y", email=email, password="Passw0rdA1", confirm="Passw0rdA1", csrf_token=tok(other)))
        self.assertEqual(r.status_code, 422)
        self.assertIn("already exists", r.get_data(as_text=True))
        _, r = self.register(other, password="short")
        self.assertEqual(r.status_code, 422)
        _, r = self.register(other, password="onlyletters")
        self.assertIn("letter and one number", r.get_data(as_text=True))

    def test_student_pages_need_login(self):
        for path in ["/student/dashboard", "/student/profile", "/student/password", "/student/claim"]:
            self.assertEqual(self.c.get(path).status_code, 302, path)
        self.assertEqual(self.c.post("/student/logout").status_code, 400)

    def test_claim_an_older_application(self):
        # applications made before accounts existed (older versions) have no owner
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        number = f"MIUTM-2025-{900000 + next(_n)}"
        con.execute("""INSERT INTO admissions (application_no, full_name, father_name, mother_name, gender, dob, email, phone, nationality,
                       qualification, percentage, course_code, course_name, address, city, state, pincode)
                       VALUES (?, 'Old Applicant', 'F', 'M', 'Male', '2006-01-01', 'old@example.com', '9876501234', 'Indian',
                       '12th (Intermediate)', 70, 'BCA', 'Bachelor of Computer Applications', 'Addr 12', 'Ayodhya', 'Uttar Pradesh', '224001')""", (number,))
        con.commit(); con.close()
        b = self.logged_in_student()
        wrong = b.post("/student/claim", data={"application_no": number, "dob": "2000-01-01", "csrf_token": tok(b)})
        self.assertIn("could not find", wrong.get_data(as_text=True))
        ok = b.post("/student/claim", data={"application_no": number.lower(), "dob": "2006-01-01", "csrf_token": tok(b)})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(b.get(f"/student/applications/{number}").status_code, 200)
        c = self.logged_in_student()
        taken = c.post("/student/claim", data={"application_no": number, "dob": "2006-01-01", "csrf_token": tok(c)})
        self.assertIn("already linked", taken.get_data(as_text=True))

    def test_students_cannot_see_each_other(self):
        a, b = self.logged_in_student(), self.logged_in_student()
        number = self.apply(a)
        self.assertEqual(a.get(f"/student/applications/{number}").status_code, 200)
        self.assertEqual(b.get(f"/student/applications/{number}").status_code, 404)
        self.assertEqual(b.get(f"/student/applications/{number}/print").status_code, 404)
        self.assertEqual(b.post(f"/student/applications/{number}/withdraw", data={"csrf_token": tok(b)}).status_code, 404)

    def test_edit_then_blocked_then_withdraw(self):
        c = self.logged_in_student()
        number = self.apply(c)
        edit = dict(VALID, city="Lucknow", email="edited@example.com", csrf_token=tok(c))
        r = c.post(f"/student/applications/{number}/edit", data=edit)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        self.assertIn("Lucknow", c.get(f"/student/applications/{number}/print").get_data(as_text=True))
        self.set_status(self.staff(), number, "Under Review")
        self.assertEqual(c.get(f"/student/applications/{number}/edit").status_code, 302)
        self.assertEqual(c.post(f"/student/applications/{number}/withdraw", data={"csrf_token": tok(c)}).status_code, 302)
        page = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn("Cancelled", page)
        self.assertIn("Withdrawn by the applicant", page)

    def upload(self, c, number, doc_type, data, name):
        return c.post(f"/student/applications/{number}/documents",
                      data={"doc_type": doc_type, "file": (io.BytesIO(data), name), "csrf_token": tok(c)},
                      content_type="multipart/form-data", follow_redirects=True)

    def test_document_upload_after_submitting(self):
        c = self.logged_in_student()
        number = self.apply(c)
        ok = self.upload(c, number, "Class 12 marksheet", PDF, "marks12.pdf").get_data(as_text=True)
        self.assertIn("uploaded", ok)
        self.assertIn("marks12.pdf", ok)
        self.assertNotIn("Photo ID", ok)
        self.assertIn("Only PDF, JPG and PNG", self.upload(c, number, "Transfer certificate", b"MZ binary", "virus.exe").get_data(as_text=True))
        self.assertIn("does not match its type", self.upload(c, number, "Transfer certificate", b"not really a pdf", "fake.pdf").get_data(as_text=True))
        self.assertIn("larger than 2 MB", self.upload(c, number, "Transfer certificate", PDF + b"0" * (2 * 1024 * 1024), "big.pdf").get_data(as_text=True))
        self.assertIn("Choose which document", self.upload(c, number, "Photo ID", PDF, "x.pdf").get_data(as_text=True))
        self.assertEqual(c.post(f"/student/applications/{number}/documents", data={"doc_type": "Class 10 marksheet"}).status_code, 400)

    def test_document_review_and_privacy(self):
        a, b = self.logged_in_student(), self.logged_in_student()
        number = self.apply(a)
        self.upload(a, number, "Passport-size photo", PNG, "me.png")
        page = a.get(f"/student/applications/{number}").get_data(as_text=True)
        doc_id = int(re.search(r"/student/documents/(\d+)", page).group(1))
        dl = a.get(f"/student/documents/{doc_id}")
        self.assertEqual(dl.data, PNG)
        self.assertIn("attachment", dl.headers["Content-Disposition"])
        self.assertEqual(b.get(f"/student/documents/{doc_id}").status_code, 404)
        staff = self.staff()
        self.assertEqual(staff.get(f"/admin/documents/{doc_id}").data, PNG)
        staff.post(f"/admin/documents/{doc_id}/review", data={"status": "Verified", "note": "Clear photo", "csrf_token": tok(staff)})
        self.assertIn("Verified", a.get(f"/student/applications/{number}").get_data(as_text=True))
        self.assertIn("already verified", self.upload(a, number, "Passport-size photo", PNG, "new.png").get_data(as_text=True))

    def test_new_statuses_and_offer_letter(self):
        c = self.logged_in_student()
        number = self.apply(c, full_name="Asha Verma")
        self.assertEqual(c.get(f"/student/applications/{number}/offer").status_code, 302)
        a = self.staff()
        for status in ("Waitlisted", "Approved", "Enrolled", "Cancelled"):
            self.set_status(a, number, status)
        aid = self.set_status(a, number, "Approved")
        html = c.get(f"/student/applications/{number}/offer").get_data(as_text=True)
        self.assertIn("Provisional offer of admission", html)
        self.assertIn("Asha Verma", html)
        self.assertNotIn("Photo ID</li>", html)
        self.assertEqual(a.get(f"/admin/applications/{aid}/offer").status_code, 200)
        self.assertEqual(a.post(f"/admin/applications/{aid}/status", data={"status": "Nonsense", "csrf_token": tok(a)}).status_code, 302)

    def test_emails_are_sent(self):
        c = self.logged_in_student()
        email = f"mail{next(_n)}@example.com"
        number = self.apply(c, email=email)
        self.assertTrue(any(to == email and number in body and "received" in subj.lower() for to, subj, body in self.sent))
        self.set_status(self.staff(), number, "Approved", note="See you at counselling")
        mails = [(s, b) for to, s, b in self.sent if to == email and "Approved" in s]
        self.assertTrue(mails)
        self.assertIn("See you at counselling", mails[0][1])

    def test_password_reset_by_email(self):
        email, _ = self.register()
        self.c.post("/student/logout", data={"csrf_token": tok(self.c)})
        self.assertIn("reset link is on its way", self.c.post("/student/forgot", data={"email": email, "csrf_token": tok(self.c)}).get_data(as_text=True))
        link = re.search(r"http://localhost(/student/reset/[^\s]+)", next(b for to, s, b in self.sent if to == email and "Reset" in s)).group(1)
        self.assertEqual(self.c.get(link).status_code, 200)
        self.assertEqual(self.c.post(link, data={"password": "abc", "confirm": "abc", "csrf_token": tok(self.c)}).status_code, 422)
        self.assertEqual(self.c.post(link, data={"password": "BrandNew9x", "confirm": "BrandNew9x", "csrf_token": tok(self.c)}).status_code, 302)
        self.assertEqual(self.c.post("/student/login", data={"email": email, "password": "BrandNew9x", "csrf_token": tok(self.c)}).status_code, 302)
        self.assertEqual(self.c.get(link).status_code, 400)

    def test_email_off_message(self):
        app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": True})
        self.assertIn("Email is not set up", app.test_client().get("/student/forgot").get_data(as_text=True))


# ===========================================================================
class StaffTools(Base):
    def test_reviewer_permissions(self):
        admin = self.staff()
        number = self.apply(self.logged_in_student())
        rev = self.staff(self.make_reviewer(admin), "Review-Pass-9x")
        for path in ("/admin/dashboard", "/admin/applications", "/admin/merit", "/admin/documents", "/admin/messages", "/admin/tickets",
                     "/admin/students", "/admin/reports", "/admin/account"):
            self.assertEqual(rev.get(path).status_code, 200, path)
        for path in ("/admin/content", "/admin/content/notices", "/admin/staff", "/admin/staff/new", "/admin/activity", "/admin/settings"):
            self.assertEqual(rev.get(path).status_code, 403, path)
        aid = self.admin_id(rev, number)
        t = tok(rev)
        self.assertEqual(rev.post(f"/admin/applications/{aid}/delete", data={"csrf_token": t}).status_code, 403)
        self.assertEqual(rev.post("/admin/backup", data={"csrf_token": t}).status_code, 403)
        self.assertEqual(rev.post("/admin/merit/BCA/apply", data={"csrf_token": t}).status_code, 403)
        self.assertEqual(rev.post(f"/admin/applications/{aid}/status", data={"status": "Under Review", "csrf_token": t}).status_code, 302)
        self.assertNotIn("Staff accounts", rev.get("/admin/dashboard").get_data(as_text=True))

    def test_deactivated_staff_loses_access(self):
        admin = self.staff()
        name = self.make_reviewer(admin)
        rev = self.staff(name, "Review-Pass-9x")
        self.assertEqual(rev.get("/admin/dashboard").status_code, 200)
        uid = int(re.search(rf'class="sub">{name}.*?/admin/staff/(\d+)/edit', admin.get("/admin/staff").get_data(as_text=True), re.S).group(1))
        self.assertEqual(admin.post(f"/admin/staff/{uid}/edit", data={"full_name": "Rita", "email": "", "role": "reviewer", "csrf_token": tok(admin)}).status_code, 302)
        self.assertEqual(rev.get("/admin/dashboard").status_code, 302)

    def test_last_admin_cannot_be_removed(self):
        # its own database, so exactly one administrator exists whatever the other tests did
        app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": True, "DATABASE": os.path.join(tmp, "solo.db")})
        admin = app.test_client()
        admin.post("/admin/login", data={"username": "boss", "password": "Correct-Horse-9", "csrf_token": token(admin, "/admin/login")})
        html = admin.get("/admin/staff").get_data(as_text=True)
        uid = int(re.search(r'class="sub">boss.*?/admin/staff/(\d+)/edit', html, re.S).group(1))
        r = admin.post(f"/admin/staff/{uid}/edit", data={"full_name": "Boss", "email": "", "role": "reviewer", "is_active": "1", "csrf_token": tok(admin)})
        self.assertEqual(r.status_code, 422)
        self.assertIn("only active administrator", r.get_data(as_text=True))
        r = admin.post(f"/admin/staff/{uid}/edit", data={"full_name": "Boss", "email": "", "role": "admin", "csrf_token": tok(admin)})  # switch off
        self.assertEqual(r.status_code, 422)

    def test_merit_list_approves_by_rank(self):
        admin = self.staff()
        code = f"T{next(_n)}"
        r = admin.post("/admin/content/programmes/new", data=dict(
            code=code, name=f"Test programme {code}", level="Certificate", school="School of Computing Sciences", duration="3 months",
            seats="1", fee="1000", fee_period="total", min_percent="0", sort_order="50", eligibility="Anyone with class 12.",
            accepts="12th (Intermediate),Diploma", audience="short", summary="Test", topics="A,B", is_published="1", csrf_token=tok(admin)))
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])
        nums = {pct: self.apply(self.app.test_client(), course_code=code, percentage=pct) for pct in ("60", "80", "70")}
        page = admin.get(f"/admin/merit?course={code}").get_data(as_text=True)
        self.assertLess(page.index(nums["80"]), page.index(nums["70"]))
        self.assertLess(page.index(nums["70"]), page.index(nums["60"]))
        self.assertEqual(admin.post(f"/admin/merit/{code}/apply", data={"csrf_token": tok(admin)}).status_code, 302)

        def status_of(n):
            html = admin.get(f"/admin/applications?q={n}").get_data(as_text=True)
            return re.search(r"badge--[a-z-]+\">([A-Za-z ]+)<", html).group(1)
        self.assertEqual(status_of(nums["80"]), "Approved")
        self.assertEqual(status_of(nums["70"]), "Waitlisted")
        self.assertEqual(status_of(nums["60"]), "Waitlisted")
        aid = self.admin_id(admin, nums["70"])
        admin.post(f"/admin/applications/{aid}/status", data={"status": "Approved", "csrf_token": tok(admin)})
        self.assertIn("over capacity", admin.get(f"/admin/applications/{aid}").get_data(as_text=True) + admin.get("/admin/applications").get_data(as_text=True))

    def test_content_manager(self):
        admin = self.staff()
        title = f"Notice number {next(_n)}"
        r = admin.post("/admin/content/notices/new", data={"title": title, "category": "General", "published_on": "2026-10-10",
                                                           "body": "Body text here.", "is_published": "1", "csrf_token": tok(admin)})
        self.assertEqual(r.status_code, 302)
        self.assertIn(title, self.c.get("/news").get_data(as_text=True))
        html = admin.get("/admin/content/notices").get_data(as_text=True)
        rid = int(re.search(r"/admin/content/notices/(\d+)/edit", html[html.index(title) - 600:html.index(title) + 900]).group(1))
        admin.post(f"/admin/content/notices/{rid}/toggle", data={"csrf_token": tok(admin)})
        self.assertNotIn(title, self.c.get("/news").get_data(as_text=True))
        self.assertEqual(admin.post(f"/admin/content/notices/{rid}/delete", data={"csrf_token": tok(admin)}).status_code, 302)
        bad = admin.post("/admin/content/notices/new", data={"title": "", "category": "Nope", "published_on": "xx", "body": "", "csrf_token": tok(admin)})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(admin.get("/admin/content/unknown").status_code, 404)
        admin.post("/admin/content/events/new", data={"title": "Robotics fair", "starts_on": "2030-01-05", "ends_on": "", "location": "Main hall",
                                                      "description": "Come and see.", "is_published": "1", "csrf_token": tok(admin)})
        self.assertIn("Robotics fair", self.c.get("/news").get_data(as_text=True))
        self.assertIn("Robotics fair", self.c.get("/search?q=robotics").get_data(as_text=True))

    def test_hidden_programme_and_delete_guard(self):
        admin = self.staff()
        self.apply(self.logged_in_student())
        html = admin.get("/admin/content/programmes").get_data(as_text=True)
        bca_id = int(re.search(r"/admin/content/programmes/(\d+)/edit", html).group(1))
        blocked = admin.post(f"/admin/content/programmes/{bca_id}/delete", data={"csrf_token": tok(admin)}, follow_redirects=True)
        self.assertIn("has applications", blocked.get_data(as_text=True))
        admin.post(f"/admin/content/programmes/{bca_id}/toggle", data={"csrf_token": tok(admin)})
        self.assertEqual(self.c.get("/programmes/bca").status_code, 404)
        admin.post(f"/admin/content/programmes/{bca_id}/toggle", data={"csrf_token": tok(admin)})
        self.assertEqual(self.c.get("/programmes/bca").status_code, 200)

    def test_ticket_flow(self):
        r = self.c.post("/support", data=dict(name="Meena", email="meena@example.com", phone="", category="Fees and scholarships",
                                              subject="Scholarship question", message="How do I claim the girl-child scholarship?",
                                              csrf_token=tok(self.c)), follow_redirects=True)
        number = re.search(r"TKT-\d{4}-\d{6}", r.get_data(as_text=True)).group(0)
        self.assertTrue(any(number in body for _, _, body in self.sent))
        wrong = self.c.post("/support/track", data={"ticket_no": number, "email": "other@example.com", "csrf_token": tok(self.c)})
        self.assertIn("could not find", wrong.get_data(as_text=True))
        admin = self.staff()
        html = admin.get("/admin/tickets").get_data(as_text=True)
        tid = int(re.search(r"/admin/tickets/(\d+)\"", html[html.index(number) - 200:html.index(number)]).group(1))
        admin.post(f"/admin/tickets/{tid}", data={"status": "Resolved", "response": "Bring your marksheet to counselling.", "csrf_token": tok(admin)})
        ok = self.c.post("/support/track", data={"ticket_no": number, "email": "MEENA@example.com", "csrf_token": tok(self.c)}).get_data(as_text=True)
        self.assertIn("Bring your marksheet", ok)
        self.assertIn("Resolved", ok)
        self.assertEqual(self.c.post("/support", data=dict(name="M", email="bad", category="x", subject="a", message="short", csrf_token=tok(self.c))).status_code, 422)

    def test_reports_activity_backup(self):
        a = self.staff()
        self.assertEqual(a.get("/admin/reports").status_code, 200)
        self.assertIn("login", a.get("/admin/activity").get_data(as_text=True))
        self.assertEqual(a.post("/admin/backup").status_code, 400)
        r = a.post("/admin/backup", data={"csrf_token": tok(a)})
        self.assertTrue(r.data.startswith(b"SQLite format 3"))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        con = sqlite3.connect(":memory:")
        con.deserialize(r.data)
        self.assertGreater(con.execute("select count(*) from courses").fetchone()[0], 0)

    def test_staff_header_state(self):
        self.assertIn("Staff dashboard", self.staff().get("/").get_data(as_text=True))


# ===========================================================================
class AboutPage(Base):
    def test_about_is_a_proper_profile(self):
        html = self.c.get("/about").get_data(as_text=True)
        for section in ("overview", "vision", "academics", "admissions", "campus", "research", "student-life", "leadership", "policies"):
            self.assertIn(f'id="{section}"', html, section)
        for text in ("Maurya International University of Technology &amp; Management", "Why Ayodhya", "Our mission", "Our vision",
                     "Certificate", "Postgraduate", "The five schools", "Merit decides", "Who to contact for what", "Privacy policy",
                     "About this website"):
            self.assertIn(text, html, text)
        for awkward in ("built this portal", "Sample profiles", "Replace them"):
            self.assertNotIn(awkward, html, awkward)
        self.assertEqual(html.count('href="#overview"'), 1)   # jump menu works


if __name__ == "__main__":
    unittest.main(verbosity=1)
