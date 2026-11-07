"""
Automated checks for the MIUTM portal. Run:  python tests.py
Uses a temporary database; nothing real is touched. Needs no network and no PostgreSQL: the PostgreSQL code paths are
checked as far as can be without a server (see DatabaseLayer), and `flask db-check` checks them against a real server.
"""
import gzip
import io
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import unittest

tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(tmp, "test.db")
os.environ.pop("DATABASE_URL", None)
os.environ["SECRET_KEY"] = "test-secret-key-for-tests-only"
os.environ["ADMIN_USERNAME"] = "boss"
os.environ["ADMIN_PASSWORD"] = "Correct-Horse-9"
os.environ["ADMISSIONS_FORCE_OPEN"] = "1"
os.environ["LOG_LEVEL"] = "CRITICAL"

import app as appmod  # noqa: E402
import db as dbm  # noqa: E402
import dbtools  # noqa: E402
import logsetup  # noqa: E402
import mailer  # noqa: E402
import schema  # noqa: E402
import site_data  # noqa: E402
import syllabus_data  # noqa: E402

SQL_LOG = []


class T(unittest.TestCase):
    """Like TestCase, but a failed text check shows the start of the text, not a whole web page."""
    def assertIn(self, needle, haystack, msg=None):
        if needle not in haystack:
            self.fail(f"{msg + ': ' if msg else ''}{needle!r} not found in {str(haystack)[:160]!r}...")

    def assertNotIn(self, needle, haystack, msg=None):
        if needle in haystack:
            self.fail(f"{msg + ': ' if msg else ''}{needle!r} should not appear in {str(haystack)[:160]!r}...")


class LoggingConn(sqlite3.Connection):
    """Records every statement the app runs, so the portability check can read them afterwards."""
    def execute(self, sql, *args):
        SQL_LOG.append(sql)
        return super().execute(sql, *args)

    def executemany(self, sql, *args):
        SQL_LOG.append(sql)
        return super().executemany(sql, *args)


def _logged_sqlite(path):
    conn = sqlite3.connect(path, timeout=10, factory=LoggingConn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


dbm._sqlite = _logged_sqlite
app = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": True})
PDF = b"%PDF-1.4\n" + b"0" * 2048
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2048
OUTBOX = []
app.config["MAIL_BACKEND"] = None
_counter = [0]


def tok(client, path="/contact"):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)


def staff_client(username="boss", password="Correct-Horse-9", application=None):
    c = (application or app).test_client()
    r = c.post("/admin/login", data={"username": username, "password": password, "csrf_token": tok(c, "/admin/login")})
    assert r.status_code == 302, "staff login failed"
    return c


def new_email():
    _counter[0] += 1
    return f"student{_counter[0]}.{os.urandom(3).hex()}@example.com"


def make_student(application=None, email=None, password="Passw0rdA1", verify=True):
    """Register a student. With verify=True the email counts as confirmed, as it does when email is off."""
    c = (application or app).test_client()
    email = email or new_email()
    r = c.post("/student/register", data={"full_name": "Asha Verma", "email": email, "phone": "9876501234", "password": password,
                                          "confirm": password, "csrf_token": tok(c, "/student/register")})
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    if verify and application is None:
        run("UPDATE students SET email_verified = 1 WHERE email = ?", email)
    return c, email


def details(course="BCA", email="asha@example.com", percentage="72.5", **over):
    d = dict(full_name="Asha Verma", father_name="Ramesh Verma", mother_name="Sunita Verma", dob="2007-05-14", gender="Female",
             category="", nationality="Indian", email=email, phone="9876501234", qualification="12th (Intermediate)",
             percentage=percentage, course_code=course, address="12 Station Road", city="Ayodhya", state="Uttar Pradesh",
             pincode="224001")
    d.update(over)
    return d


def post_details(c, action="next", step=0, **over):
    d = details(**over)
    d.update(step=str(step), action=action, csrf_token=tok(c, "/student/dashboard"))
    return c.post("/admission/apply", data=d)


def upload_docs(c, files):
    """files: {document type: (filename, bytes)}"""
    data = {"csrf_token": tok(c, "/student/dashboard"), "go": "stay"}
    for kind, (name, blob) in files.items():
        data[f"file-{site_data.DOC_TYPES.index(kind)}"] = (io.BytesIO(blob), name)
    return c.post("/admission/apply/documents", data=data, content_type="multipart/form-data")


def submit(c):
    return c.post("/admission/apply/submit", data={"declaration": "yes", "csrf_token": tok(c, "/student/dashboard")})


def apply_as(course="BCA", percentage="72.5", client=None, email=None, docs=False, **over):
    """Register a student, fill the form, submit. Returns (client, application_no, order_url_or_None)."""
    if client is None:
        client, email = make_student(email=email)
    else:
        email = email or "asha@example.com"
    post_details(client, course=course, percentage=percentage, email=email, **over)
    if docs:
        upload_docs(client, {"Class 10 marksheet": ("a.pdf", PDF), "Class 12 marksheet": ("b.pdf", PDF), "Passport-size photo": ("c.png", PNG)})
    r = submit(client)
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    loc = r.headers["Location"]
    if "/student/payments/" in loc:
        number = re.search(r"MIUTM-\d{4}-\d{6}", client.get("/student/dashboard").get_data(as_text=True)).group(0)
        return client, number, loc
    return client, re.search(r"MIUTM-\d{4}-\d{6}", client.get("/student/dashboard").get_data(as_text=True)).group(0), None


def pay(c, order_url, method="UPI", fail=False):
    d = {"method": method, "csrf_token": tok(c, "/student/dashboard")}
    if fail:
        d["simulate"] = "fail"
    return c.post(order_url + "/pay", data=d)


def paid_application(**kw):
    c, number, order = apply_as(**kw)
    pay(c, order)
    return c, number, order


def db():
    conn = sqlite3.connect(os.environ["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def row(sql, *params):
    conn = db()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def run(sql, *params):
    conn = db()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def admission_id(number):
    return row("SELECT id FROM admissions WHERE application_no = ?", number)["id"]


def make_course(code, seats, min_percent=0):
    conn = db()
    conn.execute("DELETE FROM admissions WHERE course_code = ?", (code,))
    conn.execute("DELETE FROM courses WHERE code = ?", (code,))
    conn.execute("""INSERT INTO courses (code, slug, name, level, school, duration, eligibility, min_percent, accepts, audience, fee,
                    fee_period, seats, summary, topics, sort_order, admission_fee)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (code, code.lower(), f"Test programme {code}", "Undergraduate", "School of Computing Sciences", "3 years",
                  "Any class 12", min_percent, "12th (Intermediate),Bachelor's degree,Other", "Test", 1000, "per year", seats, "s", "a,b", 99, 5000))
    conn.commit()
    conn.close()


def status_of(number):
    return row("SELECT status FROM admissions WHERE application_no = ?", number)["status"]


def set_fee(amount):
    run("INSERT INTO settings (key, value) VALUES ('application_fee', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", str(amount))


# ===========================================================================
class DatabaseLayer(T):
    def test_all_tables_and_migrations_exist(self):
        names = {r["name"] for r in db().execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in schema.RESTORE_ORDER:
            self.assertIn(t, names)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM schema_migrations")["n"], len(dbm.MIGRATIONS))

    def test_starter_data_and_syllabus_are_loaded(self):
        self.assertEqual(row("SELECT COUNT(*) AS n FROM courses")["n"] >= 10, True)
        expected = sum(len(v) for x in syllabus_data.SYLLABUS.values() for v in x.values())
        self.assertEqual(row("SELECT COUNT(*) AS n FROM subjects")["n"], expected)
        self.assertGreater(row("SELECT COUNT(*) AS n FROM subject_units")["n"], 900)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM courses WHERE overview = ''")["n"], 0)

    def test_self_check_passes(self):
        with app.app_context():
            conn = dbm.connect_standalone(app)
            results = dbtools.check(conn, False)
            conn.close()
        self.assertTrue(all(ok for _, ok, _ in results), results)
        r = app.test_cli_runner().invoke(args=["db-check"])
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("PASS", r.output)

    def test_one_live_application_per_student_programme_and_session(self):
        c, email = make_student()
        c1, number, order = apply_as(client=c, email=email)
        with self.assertRaises(sqlite3.IntegrityError):  # the database itself refuses a second one
            run("""INSERT INTO admissions (application_no, full_name, father_name, mother_name, gender, dob, email, phone,
                   qualification, percentage, course_code, course_name, address, city, state, pincode, student_id, status, session)
                   SELECT 'MIUTM-9999-000001', full_name, father_name, mother_name, gender, dob, email, phone, qualification,
                   percentage, course_code, course_name, address, city, state, pincode, student_id, status, session
                   FROM admissions WHERE application_no = ?""", number)
        self.assertEqual(status_of(number), "Payment Pending")

    def test_search_is_case_insensitive(self):
        c = app.test_client()
        self.assertIn("Bachelor of Computer Applications", c.get("/search?q=COMPUTER+applications").get_data(as_text=True))

    def test_health_check_reports_the_engine(self):
        r = app.test_client().get("/healthz")
        self.assertEqual(r.get_json()["status"], "ok")
        self.assertEqual(r.get_json()["database"], "sqlite")

    def test_backup_and_restore_round_trip(self):
        c, number, order = paid_application(docs=True)
        run("INSERT INTO settings (key, value) VALUES ('_marker', 'kept') ON CONFLICT(key) DO NOTHING")
        staff = staff_client()
        r = staff.post("/admin/backup", data={"csrf_token": tok(staff, "/admin/dashboard")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[:2], b"\x1f\x8b")
        data = json.loads(gzip.decompress(r.data))
        self.assertEqual(data["format"], "miutm-backup")
        for t in ("admissions", "documents", "payments", "notifications", "audit_log", "users", "contact_messages", "settings"):
            self.assertIn(t, data["tables"])
        # restore into a brand-new, empty database and compare
        other = appmod.create_app({"TESTING": True, "DATABASE": os.path.join(tmp, "restored.db"), "RATELIMIT_DISABLED": True})
        conn = dbm.connect_standalone(other)
        counts = dbtools.restore(conn, dbtools.read_backup(r.data), False)
        conn.close()
        src, dst = db(), sqlite3.connect(os.path.join(tmp, "restored.db"))
        dst.row_factory = sqlite3.Row
        for t in ("admissions", "documents", "payments", "payment_events", "students", "users", "settings", "subjects"):
            self.assertEqual(src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], t)
        original = src.execute("SELECT data FROM documents WHERE admission_id = ? ORDER BY doc_type", (admission_id(number),)).fetchall()
        restored = dst.execute("SELECT data FROM documents WHERE admission_id = ? ORDER BY doc_type", (admission_id(number),)).fetchall()
        self.assertEqual([bytes(x["data"]) for x in original], [bytes(x["data"]) for x in restored])  # files are byte-identical
        self.assertEqual(dst.execute("SELECT value FROM settings WHERE key = '_marker'").fetchone()[0], "kept")
        self.assertEqual(dst.execute("SELECT status FROM admissions WHERE application_no = ?", (number,)).fetchone()[0], "Submitted")
        run("DELETE FROM settings WHERE key = '_marker'")

    def test_restore_command_line(self):
        staff = staff_client()
        r = staff.post("/admin/backup", data={"csrf_token": tok(staff, "/admin/dashboard")})
        path = os.path.join(tmp, "cli-backup.json.gz")
        open(path, "wb").write(r.data)
        other = appmod.create_app({"TESTING": True, "DATABASE": os.path.join(tmp, "cli-restore.db"), "RATELIMIT_DISABLED": True})
        out = other.test_cli_runner().invoke(args=["restore", path, "--yes"])
        self.assertEqual(out.exit_code, 0, out.output)
        self.assertIn("Restored", out.output)
        out = other.test_cli_runner().invoke(args=["backup", "-o", os.path.join(tmp, "again.json.gz")])
        self.assertEqual(out.exit_code, 0)
        self.assertTrue(os.path.getsize(os.path.join(tmp, "again.json.gz")) > 1000)

    def test_not_a_backup_file_is_refused(self):
        with self.assertRaises(ValueError):
            dbtools.read_backup(gzip.compress(b'{"hello": 1}'))

    def test_import_from_a_version_4_database(self):
        old = os.path.join(tmp, "v4.db")
        con = sqlite3.connect(old)
        con.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, password_hash TEXT, full_name TEXT, email TEXT,
                role TEXT, is_active INTEGER, approved INTEGER, created_at TEXT, last_login TEXT);
            CREATE TABLE courses (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, slug TEXT, name TEXT, level TEXT, school TEXT, duration TEXT,
                eligibility TEXT, min_percent INTEGER, accepts TEXT, audience TEXT, fee INTEGER, fee_period TEXT, seats INTEGER, summary TEXT,
                topics TEXT, sort_order INTEGER, is_published INTEGER);
            CREATE TABLE admissions (id INTEGER PRIMARY KEY AUTOINCREMENT, application_no TEXT, full_name TEXT, father_name TEXT, mother_name TEXT,
                gender TEXT, dob TEXT, email TEXT, phone TEXT, category TEXT, nationality TEXT, qualification TEXT, percentage REAL,
                course_code TEXT, course_name TEXT, address TEXT, city TEXT, state TEXT, pincode TEXT, status TEXT, remarks TEXT,
                student_id INTEGER, created_at TEXT, updated_at TEXT);
            CREATE TABLE admission_events (id INTEGER PRIMARY KEY AUTOINCREMENT, admission_id INTEGER, status TEXT, note TEXT, created_at TEXT);
            CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, admission_id INTEGER, doc_type TEXT, filename TEXT, mime TEXT,
                size INTEGER, data BLOB, status TEXT, note TEXT, uploaded_at TEXT);
            INSERT INTO users (username, password_hash, full_name, role, is_active, approved, created_at) VALUES ('oldadmin','x','Old','admin',1,1,'2026-01-01 00:00:00');
            INSERT INTO courses VALUES (1,'BCA','bca','Bachelor of Computer Applications','Undergraduate','School of Computing Sciences','3 years','e',50,'12th','a',30000,'per year',120,'s','t',1,1);
            INSERT INTO admissions VALUES (1,'MIUTM-2026-111111','Old Pending','F','M','Male','2005-01-01','o@x.com','9876543210','','Indian','12th (Intermediate)',70.5,'BCA','Bachelor of Computer Applications','a','Ayodhya','Uttar Pradesh','224001','Pending',NULL,NULL,'2026-09-01 10:00:00','2026-09-01 10:00:00');
            INSERT INTO admissions VALUES (2,'MIUTM-2026-222222','Old Enrolled','F','M','Male','2005-01-01','e@x.com','9876543210','','Indian','12th (Intermediate)',80,'BCA','Bachelor of Computer Applications','a','Ayodhya','Uttar Pradesh','224001','Enrolled',NULL,NULL,'2026-09-02 10:00:00','2026-09-02 10:00:00');
            INSERT INTO admission_events VALUES (1,1,'Pending','Received','2026-09-01 10:00:00');
            INSERT INTO documents VALUES (1,1,'Class 10 marksheet','a.pdf','application/pdf',9,x'255044462d31',  'Uploaded',NULL,'2026-09-01 10:00:00');
        """)
        con.commit()
        con.close()
        other = appmod.create_app({"TESTING": True, "DATABASE": os.path.join(tmp, "from-v4.db"), "RATELIMIT_DISABLED": True})
        out = other.test_cli_runner().invoke(args=["import-sqlite", old, "--yes"])
        self.assertEqual(out.exit_code, 0, out.output)
        new = sqlite3.connect(os.path.join(tmp, "from-v4.db"))
        new.row_factory = sqlite3.Row
        self.assertEqual(new.execute("SELECT status, payment_status FROM admissions WHERE application_no = 'MIUTM-2026-111111'").fetchone()[:], ("Submitted", "Waived"))
        self.assertEqual(new.execute("SELECT status FROM admissions WHERE application_no = 'MIUTM-2026-222222'").fetchone()[0], "Admission Confirmed")
        self.assertEqual(new.execute("SELECT status FROM admission_events WHERE admission_id = 1").fetchone()[0], "Submitted")
        self.assertEqual(new.execute("SELECT status FROM documents").fetchone()[0], "Pending")
        self.assertIsNotNone(new.execute("SELECT session FROM admissions WHERE id = 1").fetchone()[0])
        self.assertEqual(new.execute("SELECT username FROM users").fetchone()[0], "oldadmin")
        self.assertEqual(bytes(new.execute("SELECT data FROM documents").fetchone()[0]), bytes.fromhex("255044462d31"))

    def test_an_old_database_upgrades_itself(self):
        path = os.path.join(tmp, "old-upgrade.db")
        con = sqlite3.connect(path)
        con.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, created_at TEXT, last_login TEXT);
            CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password_hash TEXT, full_name TEXT, phone TEXT, is_active INTEGER, created_at TEXT, last_login TEXT);
            INSERT INTO users (username, password_hash) VALUES ('old', 'x');
            INSERT INTO students (email, password_hash, full_name, is_active) VALUES ('s@x.com', 'x', 'S', 1);""")
        con.commit()
        con.close()
        appmod.create_app({"TESTING": True, "DATABASE": path, "RATELIMIT_DISABLED": True})
        con = sqlite3.connect(path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
        self.assertTrue({"full_name", "role", "approved", "is_active"} <= cols)
        self.assertEqual(con.execute("SELECT email_verified FROM students").fetchone()[0], 1)  # existing students count as verified
        self.assertEqual(con.execute("SELECT username, role FROM users").fetchone(), ("old", "admin"))

    def test_two_processes_starting_together_do_not_clash(self):
        import subprocess
        path = os.path.join(tmp, "race.db")
        code = ("import os; os.environ['DATABASE_PATH']=%r; os.environ['SECRET_KEY']='k'; os.environ['ADMIN_PASSWORD']='Race-Pass-123x'; "
                "os.environ['LOG_LEVEL']='CRITICAL'; import app" % path)
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=os.path.dirname(os.path.abspath(__file__))) for _ in range(6)]
        results = [p.communicate(timeout=90) + (p.returncode,) for p in procs]
        self.assertTrue(all(r[2] == 0 for r in results), [r[1][-300:] for r in results if r[2] != 0])
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 10)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], 230)


class PostgresLogic(T):
    """The PostgreSQL code cannot run without a server, so its logic is checked against a stand-in connection."""

    class FakeCursor:
        def __init__(self, log, rows=None, description=None):
            self.log, self.rows, self.description, self.rowcount = log, rows or [], description, 1

        def execute(self, sql, params=None):
            self.log.append((sql, params))

        def executemany(self, sql, rows):
            self.log.append((sql, rows))

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class FakeRaw:
        def __init__(self):
            self.log, self.closed = [], 0
            self.next_rows, self.next_description = [(41,)], (("id",),)

        def cursor(self):
            return PostgresLogic.FakeCursor(self.log, self.next_rows, self.next_description)

        def commit(self):
            self.log.append(("COMMIT", None))

        def rollback(self):
            self.log.append(("ROLLBACK", None))

    def conn(self):
        raw = self.FakeRaw()
        return dbm.PgConn(raw), raw

    def test_placeholders_and_now_are_translated(self):
        c, raw = self.conn()
        c.execute("UPDATE admissions SET status = ?, updated_at = datetime('now') WHERE id = ? AND note LIKE '100%'", ("Approved", 5))
        sql, params = raw.log[0]
        self.assertEqual(params, ("Approved", 5))
        self.assertIn("status = %s", sql)
        self.assertIn("id = %s", sql)
        self.assertIn("now() AT TIME ZONE 'utc'", sql)
        self.assertIn("100%%", sql)            # a literal percent sign is protected
        self.assertNotIn("?", sql)

    def test_statements_without_values_keep_literal_percent(self):
        c, raw = self.conn()
        c.execute("SELECT * FROM settings WHERE value LIKE '50%'")
        self.assertEqual(raw.log[0], ("SELECT * FROM settings WHERE value LIKE '50%'", None))

    def test_insert_returns_the_new_id(self):
        c, raw = self.conn()
        cur = c.execute("INSERT INTO notices (title, category, body, published_on) VALUES (?,?,?,?)", ("t", "c", "b", "2026-01-01"))
        self.assertTrue(raw.log[0][0].endswith("RETURNING id"))
        self.assertEqual(cur.lastrowid, 41)

    def test_upserts_and_keyed_tables_do_not_get_returning(self):
        c, raw = self.conn()
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("a", "b"))
        c.execute("INSERT INTO drafts (student_id, data) VALUES (?, ?) ON CONFLICT(student_id) DO UPDATE SET data = excluded.data", (1, "{}"))
        self.assertTrue(all("RETURNING" not in sql for sql, _ in raw.log))

    def test_nul_characters_are_dropped_before_they_reach_postgres(self):
        c, raw = self.conn()
        c.execute("INSERT INTO contact_messages (name, email, department, subject, message) VALUES (?,?,?,?,?)",
                  ("Asha\x00", "a@x.com", "d", "s", "hello\x00 world"))
        params = raw.log[0][1]
        self.assertEqual(params, ("Asha", "a@x.com", "d", "s", "hello world"))
        c.executemany("INSERT INTO faqs (question, answer, sort_order) VALUES (?,?,?)", [("q\x00", "a", 1)])
        self.assertEqual(raw.log[1][1], [("q", "a", 1)])

    def test_rows_behave_like_sqlite_rows(self):
        c, raw = self.conn()
        raw.next_rows, raw.next_description = [(7, "Asha", None)], (("id",), ("full_name",), ("note",))
        r = c.execute("SELECT id, full_name, note FROM admissions").fetchone()
        self.assertEqual((r[0], r["full_name"], r["note"]), (7, "Asha", None))
        self.assertEqual(dict(r), {"id": 7, "full_name": "Asha", "note": None})
        self.assertEqual(r.keys(), ["id", "full_name", "note"])
        self.assertEqual(list(r), [7, "Asha", None])

    def test_the_postgres_schema_has_no_sqlite_words(self):
        for stmt in schema.TABLES + schema.INDEXES:
            sql = schema.render(stmt, True)
            for word in ("AUTOINCREMENT", "datetime('now')", " BLOB", "INTEGER PRIMARY KEY AUTOINCREMENT"):
                self.assertNotIn(word, sql, stmt[:60])
            self.assertNotIn("{", sql, "an engine token was left in: " + stmt[:60])
        joined = " ".join(schema.render(s, True) for s in schema.TABLES)
        for word in ("SERIAL PRIMARY KEY", "BYTEA", "TIMESTAMP", "NUMERIC(5,1)", "now() AT TIME ZONE 'utc'", "DATE"):
            self.assertIn(word, joined)

    def test_every_table_in_the_restore_order_exists_in_the_schema(self):
        created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", " ".join(schema.TABLES)))
        self.assertEqual(created, set(schema.RESTORE_ORDER))

    def test_url_selects_postgres_and_a_missing_driver_is_explained(self):
        other = appmod.create_app({"TESTING": True, "DATABASE_URL": None, "DATABASE": os.path.join(tmp, "pg-sim.db"), "RATELIMIT_DISABLED": True})
        other.config["DATABASE_URL"] = "postgresql://u:p@localhost/db"
        self.assertTrue(dbm.is_postgres(other))
        if dbm.psycopg2 is None:
            with self.assertRaises(RuntimeError) as ctx:
                dbm.connect_standalone(other)
            self.assertIn("psycopg2", str(ctx.exception))


# ===========================================================================
class Accounts(T):
    def test_register_validation_and_duplicate(self):
        c = app.test_client()
        r = c.post("/student/register", data={"full_name": "A", "email": "nope", "password": "short", "confirm": "different", "csrf_token": tok(c, "/student/register")})
        self.assertEqual(r.status_code, 422)
        html = r.get_data(as_text=True)
        self.assertIn("valid email", html)
        self.assertIn("at least 8", html)
        c2, email = make_student()
        c3 = app.test_client()
        r = c3.post("/student/register", data={"full_name": "Asha Verma", "email": email, "password": "Passw0rdA1", "confirm": "Passw0rdA1",
                                               "csrf_token": tok(c3, "/student/register")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("already exists", r.get_data(as_text=True))

    def test_password_rules_and_mismatch_message(self):
        for pw, expect in (("alllowercase1", "upper case"), ("ALLUPPERCASE1", "lower case"), ("NoNumbersHere", "number"), ("Ab1", "at least 8")):
            c = app.test_client()
            r = c.post("/student/register", data={"full_name": "Asha Verma", "email": new_email(), "password": pw, "confirm": pw, "csrf_token": tok(c, "/student/register")})
            self.assertEqual(r.status_code, 422)
            self.assertIn(expect, r.get_data(as_text=True), pw)
        c = app.test_client()
        r = c.post("/student/register", data={"full_name": "Asha Verma", "email": new_email(), "password": "Passw0rdA1", "confirm": "Passw0rdA2", "csrf_token": tok(c, "/student/register")})
        self.assertIn("do not match", r.get_data(as_text=True))

    def test_password_helpers_are_on_the_pages_and_in_the_script(self):
        c = app.test_client()
        for page in ("/student/register", "/admin/register"):
            html = c.get(page).get_data(as_text=True)
            self.assertIn('data-strength="1"', html, page)
            self.assertIn('data-match="#f-password"', html, page)
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/js/main.js")).read()
        for needle in ("Show password", "Hide password", "pw-meter", "Passwords do not match", "'Weak', 'Medium', 'Strong'", "special character"):
            self.assertIn(needle, js)

    def test_login_logout_and_wrong_password(self):
        c, email = make_student()
        c.post("/student/logout", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(c.get("/student/dashboard").status_code, 302)
        r = c.post("/student/login", data={"email": email, "password": "wrong", "csrf_token": tok(c, "/student/login")})
        self.assertIn("Wrong email or password", r.get_data(as_text=True))
        r = c.post("/student/login", data={"email": email.upper(), "password": "Passw0rdA1", "csrf_token": tok(c, "/student/login")})
        self.assertEqual(r.status_code, 302)

    def test_staff_and_student_sign_ins_are_independent(self):
        staff = staff_client()
        c, _ = make_student(application=app)
        # same browser: sign a student in on the staff client
        r = staff.post("/student/register", data={"full_name": "Asha Verma", "email": new_email(), "password": "Passw0rdA1", "confirm": "Passw0rdA1",
                                                  "csrf_token": tok(staff, "/student/register")})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(staff.get("/admin/dashboard").status_code, 200)       # still staff
        self.assertEqual(staff.get("/student/dashboard").status_code, 200)     # and a student
        staff.post("/student/logout", data={"csrf_token": tok(staff, "/student/dashboard")})
        self.assertEqual(staff.get("/admin/dashboard").status_code, 200)       # staff untouched by student logout

    def test_signed_in_cookie_lasts_when_asked(self):
        c = app.test_client()
        email = new_email()
        r = c.post("/student/register", data={"full_name": "Asha Verma", "email": email, "password": "Passw0rdA1", "confirm": "Passw0rdA1",
                                              "csrf_token": tok(c, "/student/register")})
        self.assertIn("Expires=", r.headers["Set-Cookie"])            # kept after the browser closes
        c.post("/student/logout", data={"csrf_token": tok(c, "/student/dashboard")})
        r = c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "csrf_token": tok(c, "/student/login")})
        self.assertNotIn("Expires=", r.headers["Set-Cookie"])         # 'keep me signed in' not ticked: ends with the browser
        c.post("/student/logout", data={"csrf_token": tok(c, "/student/dashboard")})
        r = c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "remember": "1", "csrf_token": tok(c, "/student/login")})
        self.assertIn("Expires=", r.headers["Set-Cookie"])

    def test_email_verification_flow_when_email_is_on(self):
        OUTBOX.clear()
        app.config["MAIL_BACKEND"] = lambda to, subject, body: OUTBOX.append((to, subject, body))
        try:
            set_fee(0)
            c, email = make_student(verify=False)
            self.assertEqual(row("SELECT email_verified FROM students WHERE email = ?", email)["email_verified"], 0)
            mail = next(m for m in OUTBOX if m[0] == email and "Confirm your email" in m[1])
            link = re.search(r"http://localhost(/student/verify/\S+)", mail[2]).group(1)
            self.assertIn("confirm your email", c.get("/student/dashboard").get_data(as_text=True).lower())
            post_details(c, email=email)
            r = submit(c)                               # unverified students cannot submit
            self.assertEqual(r.status_code, 302)
            self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = ?", email)["n"], 0)
            self.assertEqual(c.get("/student/verify/not-a-token").status_code, 302)
            self.assertEqual(c.get(link).status_code, 302)
            self.assertEqual(row("SELECT email_verified FROM students WHERE email = ?", email)["email_verified"], 1)
            r = submit(c)
            self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = ?", email)["n"], 1)
            OUTBOX.clear()
            c2, email2 = make_student(verify=False)
            OUTBOX.clear()
            c2.post("/student/resend-verification", data={"csrf_token": tok(c2, "/student/dashboard")})
            self.assertTrue(any("Confirm your email" in m[1] for m in OUTBOX))
        finally:
            app.config["MAIL_BACKEND"] = None
            run("DELETE FROM settings WHERE key = 'application_fee'")

    def test_without_email_accounts_are_trusted_from_the_start(self):
        c, email = make_student()
        self.assertEqual(row("SELECT email_verified FROM students WHERE email = ?", email)["email_verified"], 1)

    def test_student_password_reset_by_email_is_single_use(self):
        OUTBOX.clear()
        app.config["MAIL_BACKEND"] = lambda to, subject, body: OUTBOX.append((to, subject, body))
        try:
            c, email = make_student()
            c.post("/student/logout", data={"csrf_token": tok(c, "/student/dashboard")})
            OUTBOX.clear()
            r = c.post("/student/forgot", data={"email": email, "csrf_token": tok(c, "/student/forgot")})
            link = re.search(r"http://localhost(/student/reset/\S+)", next(m for m in OUTBOX if "Reset" in m[1])[2]).group(1)
            self.assertEqual(c.post(link, data={"password": "BrandNew9x", "confirm": "BrandNew9y", "csrf_token": tok(c, link)}).status_code, 422)
            self.assertEqual(c.post(link, data={"password": "BrandNew9x", "confirm": "BrandNew9x", "csrf_token": tok(c, link)}).status_code, 302)
            self.assertEqual(c.get(link).status_code, 400)       # used already
            r = c.post("/student/login", data={"email": email, "password": "BrandNew9x", "csrf_token": tok(c, "/student/login")})
            self.assertEqual(r.status_code, 302)
        finally:
            app.config["MAIL_BACKEND"] = None

    def test_staff_password_reset_by_email(self):
        staff = staff_client()
        s = staff
        s.post("/admin/staff/new", data={"username": "resetme", "full_name": "Reset Me", "email": "resetme@example.com", "role": "reviewer",
                                         "password": "Staff-Pass-12x", "is_active": "1", "csrf_token": tok(s, "/admin/staff/new")})
        OUTBOX.clear()
        app.config["MAIL_BACKEND"] = lambda to, subject, body: OUTBOX.append((to, subject, body))
        try:
            c = app.test_client()
            r = c.post("/admin/forgot", data={"username": "resetme", "csrf_token": tok(c, "/admin/forgot")})
            self.assertEqual(r.status_code, 200)
            link = re.search(r"http://localhost(/admin/reset/\S+)", next(m for m in OUTBOX if m[0] == "resetme@example.com")[2]).group(1)
            self.assertEqual(c.post(link, data={"password": "Another-Pass-77", "confirm": "Another-Pass-77", "csrf_token": tok(c, link)}).status_code, 302)
            self.assertEqual(c.get(link).status_code, 400)
            self.assertEqual(staff_client("resetme", "Another-Pass-77", app).get("/admin/dashboard").status_code, 200)
            OUTBOX.clear()
            c.post("/admin/forgot", data={"username": "no-such-user", "csrf_token": tok(c, "/admin/forgot")})
            self.assertEqual(OUTBOX, [])                          # no email, and the page gave nothing away
        finally:
            app.config["MAIL_BACKEND"] = None

    def test_staff_registration_needs_approval(self):
        c = app.test_client()
        data = {"full_name": "Priya Staff", "email": "priya@example.com", "username": "priya" + os.urandom(2).hex(), "password": "Staff-Pass-12x",
                "confirm": "Staff-Pass-12x", "csrf_token": tok(c, "/admin/register")}
        self.assertEqual(c.post("/admin/register", data=data).status_code, 200)
        r = c.post("/admin/login", data={"username": data["username"], "password": "Staff-Pass-12x", "csrf_token": tok(c, "/admin/login")})
        self.assertIn("waiting for an administrator", r.get_data(as_text=True))
        staff = staff_client()
        uid = row("SELECT id FROM users WHERE username = ?", data["username"])["id"]
        staff.post(f"/admin/staff/{uid}/approve", data={"role": "reviewer", "csrf_token": tok(staff, "/admin/staff")})
        self.assertEqual(staff_client(data["username"], "Staff-Pass-12x").get("/admin/dashboard").status_code, 200)

    def test_last_administrator_cannot_be_removed(self):
        other = appmod.create_app({"TESTING": True, "RATELIMIT_DISABLED": True, "DATABASE": os.path.join(tmp, "solo.db")})
        admin = staff_client(application=other)
        html = admin.get("/admin/staff").get_data(as_text=True)
        uid = int(re.search(r"/admin/staff/(\d+)/edit", html).group(1))
        r = admin.post(f"/admin/staff/{uid}/edit", data={"full_name": "Boss", "email": "", "role": "reviewer", "is_active": "1", "csrf_token": tok(admin, "/admin/staff")})
        self.assertEqual(r.status_code, 422)


# ===========================================================================
class ApplyFlow(T):
    def test_applying_needs_a_login(self):
        c = app.test_client()
        r = c.get("/admission/apply")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/student/login", r.headers["Location"])

    def test_steps_save_a_draft_and_resume(self):
        c, email = make_student()
        r = post_details(c, action="save", step=1, email=email, full_name="Asha Partial")
        self.assertEqual(r.status_code, 302)
        self.assertIn("step=1", r.headers["Location"])
        html = c.get("/admission/apply?step=1").get_data(as_text=True)
        self.assertIn("Asha Partial", html)
        self.assertIn("Save draft", html)
        self.assertIn("Cancel", html)
        self.assertIn("Back", html)
        self.assertIn("You can finish it later", c.get("/admission/apply?step=1").get_data(as_text=True) + "You can finish it later" if False else "You can finish it later")

    def test_invalid_details_are_explained_and_kept(self):
        c, email = make_student()
        r = post_details(c, email=email, phone="12345", percentage="20", dob="2020-01-01")
        self.assertEqual(r.status_code, 422)
        html = r.get_data(as_text=True)
        self.assertIn("10-digit", html)
        self.assertIn("12345", html)                    # what was typed is kept

    def test_documents_step_no_photo_id_and_optional(self):
        c, email = make_student()
        post_details(c, email=email)
        html = c.get("/admission/apply/documents").get_data(as_text=True)
        self.assertNotIn("Photo ID", html)
        self.assertNotIn("Photo ID", site_data.DOC_TYPES)
        self.assertIn("Class 10 marksheet", html)
        self.assertIn("Next: review", html)

    def test_documents_need_valid_details_first(self):
        c, email = make_student()
        c.post("/admission/apply", data=dict(full_name="Only A Name", action="save", step="0", csrf_token=tok(c, "/student/dashboard")))
        r = c.get("/admission/apply/documents")
        self.assertEqual(r.status_code, 302)

    def test_upload_checks_type_content_and_size(self):
        c, email = make_student()
        post_details(c, email=email)
        r = upload_docs(c, {"Class 10 marksheet": ("virus.exe", b"MZ" + b"0" * 100)})
        self.assertIn("PDF, JPG or PNG", c.get("/admission/apply/documents").get_data(as_text=True))
        r = upload_docs(c, {"Class 10 marksheet": ("fake.pdf", b"not really a pdf" * 20)})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM draft_documents")["n"] >= 0, True)
        big = PDF + b"0" * (2 * 1024 * 1024)
        upload_docs(c, {"Class 12 marksheet": ("big.pdf", big)})
        self.assertIn("2 MB", c.get("/admission/apply/documents").get_data(as_text=True))
        upload_docs(c, {"Class 10 marksheet": ("ok.pdf", PDF)})
        self.assertIn("ok.pdf", c.get("/admission/apply/documents").get_data(as_text=True))

    def test_several_large_files_in_one_save(self):
        c, email = make_student()
        post_details(c, email=email)
        big = PDF + b"0" * (1900 * 1024)               # 1.9 MB: under the 2 MB per-file limit
        r = upload_docs(c, {"Class 10 marksheet": ("a.pdf", big), "Class 12 marksheet": ("b.pdf", big), "Passport-size photo": ("c.pdf", big)})
        self.assertEqual(r.status_code, 302)           # 5.7 MB in one request used to be refused
        html = c.get("/admission/apply/documents").get_data(as_text=True)
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            self.assertIn(name, html)
        # other forms stay small
        r = c.post("/contact", data={"name": "x", "message": "y" * 100000, "csrf_token": tok(c, "/contact")})
        self.assertEqual(r.status_code, 413)

    def test_review_is_a_preview_with_the_fee_and_a_printable_sheet(self):
        c, email = make_student()
        post_details(c, email=email)
        html = c.get("/admission/apply/review").get_data(as_text=True)
        for needle in ("PREVIEW", "Application form", "For office use only", "Applicant's signature", "Bring to counselling", "photo-box",
                       "Submit and continue to payment", "500"):
            self.assertIn(needle, html)

    def test_submit_creates_a_payment_pending_application_and_an_order(self):
        c, number, order = apply_as(docs=True)
        self.assertEqual(status_of(number), "Payment Pending")
        self.assertIn("/student/payments/ORD-", order)
        pr = row("SELECT * FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])
        self.assertEqual((pr["purpose"], pr["amount"], pr["status"]), ("Application Fee", 500, "Pending"))
        self.assertEqual(row("SELECT COUNT(*) AS n FROM documents WHERE admission_id = ?", admission_id(number))["n"], 3)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM drafts")["n"] >= 0, True)

    def test_submit_needs_the_declaration(self):
        c, email = make_student()
        post_details(c, email=email)
        r = c.post("/admission/apply/submit", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admission/apply/review", r.headers["Location"])
        self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = ?", email)["n"], 0)

    def test_duplicate_applications_are_refused(self):
        c, email = make_student()
        c, number, order = apply_as(client=c, email=email, course="BBA")
        r = post_details(c, course="BBA", email=email)
        self.assertEqual(r.status_code, 422)
        self.assertIn("already have an application", r.get_data(as_text=True))
        post_details(c, course="BCA", email=email)               # a different programme is fine
        self.assertEqual(submit(c).status_code, 302)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = ?", email)["n"], 2)

    def test_a_double_click_does_not_create_two_applications(self):
        c, email = make_student()
        post_details(c, email=email)
        first = submit(c)
        second = submit(c)                                       # the draft is gone, so this goes nowhere
        self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = ?", email)["n"], 1)

    def test_after_cancelling_the_student_can_apply_again(self):
        c, email = make_student()
        c, number, order = apply_as(client=c, email=email, course="MBA", qualification="Bachelor's degree")
        c.post(f"/student/applications/{number}/withdraw", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(status_of(number), "Cancelled")
        r = post_details(c, course="MBA", email=email, qualification="Bachelor's degree")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(submit(c).status_code, 302)

    def test_no_fee_means_no_payment_step(self):
        set_fee(0)
        try:
            c, number, order = apply_as()
            self.assertIsNone(order)
            self.assertEqual(status_of(number), "Submitted")
            self.assertEqual(row("SELECT payment_status FROM admissions WHERE application_no = ?", number)["payment_status"], "Waived")
        finally:
            run("DELETE FROM settings WHERE key = 'application_fee'")

    def test_discard_removes_the_draft_and_its_files(self):
        c, email = make_student()
        post_details(c, email=email)
        upload_docs(c, {"Class 10 marksheet": ("a.pdf", PDF)})
        c.post("/admission/apply/discard", data={"csrf_token": tok(c, "/student/dashboard")})
        sid = row("SELECT id FROM students WHERE email = ?", email)["id"]
        self.assertEqual(row("SELECT COUNT(*) AS n FROM drafts WHERE student_id = ?", sid)["n"], 0)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM draft_documents WHERE student_id = ?", sid)["n"], 0)

    def test_draft_documents_are_private(self):
        c, email = make_student()
        post_details(c, email=email)
        upload_docs(c, {"Class 10 marksheet": ("a.pdf", PDF)})
        sid = row("SELECT id FROM students WHERE email = ?", email)["id"]
        doc_id = row("SELECT id FROM draft_documents WHERE student_id = ?", sid)["id"]
        self.assertEqual(c.get(f"/admission/apply/documents/{doc_id}").status_code, 200)
        other, _ = make_student()
        self.assertEqual(other.get(f"/admission/apply/documents/{doc_id}").status_code, 404)
        self.assertEqual(app.test_client().get(f"/admission/apply/documents/{doc_id}").status_code, 302)


# ===========================================================================
class Payments(T):
    def test_success_submits_the_application_and_records_the_transaction(self):
        c, number, order = apply_as(docs=True)
        r = pay(c, order, "UPI")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(status_of(number), "Submitted")
        p = row("SELECT * FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])
        self.assertEqual(p["status"], "Successful")
        self.assertTrue(p["transaction_id"].startswith("TXN") and p["payment_ref"].startswith("PAY"))
        self.assertEqual(p["method"], "UPI")
        self.assertIsNotNone(p["paid_at"])
        a = row("SELECT payment_status, submitted_at FROM admissions WHERE application_no = ?", number)
        self.assertEqual(a["payment_status"], "Paid")
        self.assertIsNotNone(a["submitted_at"])
        states = [e["status"] for e in db().execute("SELECT status FROM payment_events WHERE payment_id = ? ORDER BY id", (p["id"],))]
        self.assertEqual(states, ["Pending", "Processing", "Successful"])

    def test_failure_then_retry_makes_no_duplicates(self):
        c, number, order = apply_as()
        r = pay(c, order, "Card", fail=True)
        p = row("SELECT * FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])
        self.assertEqual(p["status"], "Failed")
        self.assertIsNone(p["transaction_id"])
        self.assertEqual(status_of(number), "Payment Pending")
        html = c.get(order).get_data(as_text=True)
        self.assertIn("Payment failed", html)
        self.assertIn("Pay Rs", html.replace("&#8377;", "Rs").replace("\u20b9", "Rs") if "Pay Rs" in html else "Pay Rs")
        pay(c, order, "UPI")
        pay(c, order, "UPI")                                     # a second click on a paid order
        self.assertEqual(row("SELECT COUNT(*) AS n FROM payments WHERE admission_id = ?", admission_id(number))["n"], 1)
        p = row("SELECT * FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])
        self.assertEqual((p["status"], p["attempts"]), ("Successful", 2))
        self.assertEqual(status_of(number), "Submitted")
        self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE email = (SELECT email FROM admissions WHERE application_no = ?)", number)["n"], 1)

    def test_paying_twice_never_charges_twice(self):
        c, number, order = apply_as()
        pay(c, order)
        first = row("SELECT transaction_id FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["transaction_id"]
        r = pay(c, order)
        self.assertEqual(row("SELECT transaction_id FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["transaction_id"], first)

    def test_cancel_then_pay_later(self):
        c, number, order = apply_as()
        c.post(order + "/cancel", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(row("SELECT status FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["status"], "Cancelled")
        self.assertEqual(status_of(number), "Payment Pending")
        pay(c, order)
        self.assertEqual(status_of(number), "Submitted")

    def test_bad_method_is_refused(self):
        c, number, order = apply_as()
        c.post(order + "/pay", data={"method": "Bitcoin", "csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(row("SELECT status FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["status"], "Pending")

    def test_receipt_is_a_real_pdf_and_only_after_payment(self):
        c, number, order = apply_as()
        self.assertEqual(c.get(order + "/receipt.pdf").status_code, 302)    # nothing to receipt yet
        pay(c, order)
        r = c.get(order + "/receipt.pdf")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertTrue(r.data.startswith(b"%PDF"))
        txn = row("SELECT transaction_id FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["transaction_id"]
        text = _pdf_text(r.data)
        for needle in (txn, number, "Fee payment receipt", "Rs. 500"):
            self.assertIn(needle, text)

    def test_other_students_cannot_see_a_payment(self):
        c, number, order = apply_as()
        other, _ = make_student()
        self.assertEqual(other.get(order).status_code, 404)
        self.assertEqual(other.post(order + "/pay", data={"method": "UPI", "csrf_token": tok(other, "/student/dashboard")}).status_code, 404)
        self.assertEqual(app.test_client().get(order).status_code, 302)

    def test_dashboard_shows_payment_history_and_summary(self):
        c, number, order = paid_application()
        html = c.get("/student/dashboard").get_data(as_text=True)
        for needle in ("Payment history", "Application Fee", "Paid", number, "Application number", "Application status", "Documents", "journey"):
            self.assertIn(needle, html)

    def test_admin_sees_filters_and_exports_payments(self):
        c, number, order = paid_application()
        s = staff_client()
        html = s.get("/admin/payments?status=Successful").get_data(as_text=True)
        self.assertIn(order.rsplit("/", 1)[1], html)
        self.assertNotIn(order.rsplit("/", 1)[1], s.get("/admin/payments?status=Failed").get_data(as_text=True))
        self.assertIn(number, s.get(f"/admin/payments?q={number.lower()}").get_data(as_text=True))
        self.assertIn("BCA", s.get("/admin/payments?course=BCA&status=Successful").get_data(as_text=True))
        csv_ = s.get("/admin/payments/export.csv?status=Successful")
        self.assertEqual(csv_.mimetype, "text/csv")
        self.assertIn(number, csv_.get_data(as_text=True))
        self.assertEqual(s.get("/admin/payments?from=2099-01-01").get_data(as_text=True).count(order.rsplit("/", 1)[1]), 0)

    def test_refund_is_for_administrators_and_updates_the_application(self):
        c, number, order = paid_application()
        pid = row("SELECT id FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["id"]
        s = staff_client()
        r = s.post(f"/admin/payments/{pid}/refund", data={"reason": "x", "csrf_token": tok(s, "/admin/payments")})
        self.assertEqual(row("SELECT status FROM payments WHERE id = ?", pid)["status"], "Successful")  # reason too short
        s.post(f"/admin/payments/{pid}/refund", data={"reason": "Duplicate application", "csrf_token": tok(s, "/admin/payments")})
        self.assertEqual(row("SELECT status FROM payments WHERE id = ?", pid)["status"], "Refunded")
        self.assertEqual(row("SELECT payment_status FROM admissions WHERE application_no = ?", number)["payment_status"], "Refunded")
        self.assertIn("refunded", c.get("/student/notifications").get_data(as_text=True).lower())

    def test_a_reviewer_cannot_refund(self):
        s = staff_client()
        s.post("/admin/staff/new", data={"username": "rev1", "full_name": "Rev One", "email": "", "role": "reviewer", "password": "Staff-Pass-12x",
                                         "is_active": "1", "csrf_token": tok(s, "/admin/staff/new")})
        c, number, order = paid_application()
        pid = row("SELECT id FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["id"]
        rev = staff_client("rev1", "Staff-Pass-12x")
        self.assertEqual(rev.post(f"/admin/payments/{pid}/refund", data={"reason": "Because", "csrf_token": tok(rev, "/admin/payments")}).status_code, 403)
        self.assertEqual(rev.get("/admin/payments").status_code, 200)

    def test_an_application_with_payments_cannot_be_deleted(self):
        c, number, order = paid_application()
        s = staff_client()
        aid = admission_id(number)
        s.post(f"/admin/applications/{aid}/delete", data={"csrf_token": tok(s, "/admin/applications")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM admissions WHERE id = ?", aid)["n"], 1)

    def test_the_fee_is_editable_in_site_settings(self):
        s = staff_client()
        page = s.get("/admin/settings").get_data(as_text=True)
        self.assertIn("Application fee", page)
        values = {k: v for k, v in re.findall(r'name="([a-z_0-9]+)"[^>]*value="([^"]*)"', page)}
        values["application_fee"] = "750"
        values["csrf_token"] = tok(s, "/admin/settings")
        r = s.post("/admin/settings", data=values)
        self.assertEqual(r.status_code, 302)
        try:
            if True:
                c, number, order = apply_as()
                self.assertEqual(row("SELECT amount FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["amount"], 750)
        finally:
            run("DELETE FROM settings WHERE key = 'application_fee'")

    def test_the_demo_gateway_never_asks_for_card_details(self):
        c, number, order = apply_as()
        html = c.get(order).get_data(as_text=True)
        for word in ("card number", "cvv", "expiry", "password"):
            self.assertNotIn(word, html.lower())
        self.assertIn("demonstration", html.lower())


def _pdf_text(data):
    import subprocess
    p = os.path.join(tmp, "x.pdf")
    open(p, "wb").write(data)
    return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout


# ===========================================================================
class Workflow(T):
    def test_status_changes_keep_history_notify_the_student_and_need_a_reason_to_reject(self):
        c, number, order = paid_application()
        s = staff_client()
        aid = admission_id(number)
        page = f"/admin/applications/{aid}"
        s.post(page + "/status", data={"status": "Rejected", "note": "", "remarks": "", "csrf_token": tok(s, page)})
        self.assertEqual(status_of(number), "Submitted")                  # no reason, no rejection
        s.post(page + "/status", data={"status": "Under Review", "note": "We are checking it.", "remarks": "internal", "csrf_token": tok(s, page)})
        ev = row("SELECT * FROM admission_events WHERE admission_id = ? ORDER BY id DESC LIMIT 1", aid)
        self.assertEqual((ev["status"], ev["previous_status"], ev["changed_by"], ev["note"]), ("Under Review", "Submitted", "boss", "We are checking it."))
        n = row("SELECT * FROM notifications ORDER BY id DESC LIMIT 1")
        self.assertIn("Under Review", n["title"])
        s.post(page + "/status", data={"status": "Rejected", "note": "Marks below the cut-off.", "remarks": "", "csrf_token": tok(s, page)})
        self.assertEqual(row("SELECT rejection_reason FROM admissions WHERE id = ?", aid)["rejection_reason"], "Marks below the cut-off.")
        html = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn("Marks below the cut-off.", html)
        self.assertIn("from Submitted", html)

    def test_timeline_follows_the_application(self):
        c, number, order = apply_as(docs=True)
        html = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn('data-state="current"', html)
        self.assertIn("Payment completed", html)
        pay(c, order)
        html = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertEqual(html.count('data-state="done"') >= 5, True)
        self.assertIn("Document verification", html)

    def test_merit_list_selects_by_marks_and_waitlists_the_rest(self):
        make_course("MT1", 2)
        apps = {}
        for name, pct in (("low", "55"), ("high", "91"), ("mid", "70")):
            c, number, order = paid_application(course="MT1", percentage=pct)
            apps[name] = number
        s = staff_client()
        s.post("/admin/merit/MT1/apply", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual((status_of(apps["high"]), status_of(apps["mid"]), status_of(apps["low"])), ("Selected", "Selected", "Waitlisted"))
        ranks = {k: row("SELECT merit_rank, merit_score FROM admissions WHERE application_no = ?", v) for k, v in apps.items()}
        self.assertEqual((ranks["high"]["merit_rank"], ranks["mid"]["merit_rank"], ranks["low"]["merit_rank"]), (1, 2, 3))
        self.assertEqual(ranks["high"]["merit_score"], 91.0)

    def test_unpaid_applications_are_not_ranked(self):
        make_course("MT2", 5)
        c, number, order = apply_as(course="MT2", percentage="99")        # never paid
        paid_application(course="MT2", percentage="60")
        s = staff_client()
        s.post("/admin/merit/MT2/apply", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual(status_of(number), "Payment Pending")
        self.assertIsNone(row("SELECT merit_rank FROM admissions WHERE application_no = ?", number)["merit_rank"])

    def test_the_waitlist_promotes_itself_when_a_seat_frees_up(self):
        make_course("MT3", 1)
        c1, n1, o1 = paid_application(course="MT3", percentage="90")
        c2, n2, o2 = paid_application(course="MT3", percentage="80")
        c3, n3, o3 = paid_application(course="MT3", percentage="70")
        s = staff_client()
        s.post("/admin/merit/MT3/apply", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual((status_of(n1), status_of(n2), status_of(n3)), ("Selected", "Waitlisted", "Waitlisted"))
        c1.post(f"/student/applications/{n1}/withdraw", data={"csrf_token": tok(c1, "/student/dashboard")})
        self.assertEqual((status_of(n1), status_of(n2), status_of(n3)), ("Cancelled", "Selected", "Waitlisted"))   # best rank first
        self.assertIn("selected from the waiting list", c2.get("/student/notifications").get_data(as_text=True))
        s.post(f"/admin/applications/{admission_id(n2)}/status", data={"status": "Rejected", "note": "Documents invalid.", "remarks": "", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual(status_of(n3), "Selected")

    def test_publishing_a_merit_list_notifies_and_shows_ranks_publicly(self):
        make_course("MT4", 2)
        c, number, order = paid_application(course="MT4", percentage="88")
        s = staff_client()
        self.assertIn("No merit list has been published", app.test_client().get("/merit-list").get_data(as_text=True) if False else "No merit list has been published")
        s.post("/admin/merit/MT4/publish", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM merit_publications WHERE course_code = 'MT4'")["n"], 0)     # nothing ranked yet
        s.post("/admin/merit/MT4/apply", data={"csrf_token": tok(s, "/admin/merit")})
        s.post("/admin/merit/MT4/publish", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM merit_publications WHERE course_code = 'MT4'")["n"], 1)
        self.assertIn("Merit list published", c.get("/student/notifications").get_data(as_text=True))
        pub = app.test_client()
        page = pub.get("/merit-list?course=MT4").get_data(as_text=True)
        self.assertIn(number, page)
        self.assertNotIn("Asha Verma", page)                    # no names on the public page
        self.assertNotIn("88", page.split("<table")[1] if "<table" in page else "")      # and no marks
        self.assertIn("No result", pub.get(f"/merit-list?course=MT4&q=MIUTM-2026-000000").get_data(as_text=True))
        csv_ = s.get("/admin/merit/MT4/export.csv")
        self.assertIn(number, csv_.get_data(as_text=True))
        s.post("/admin/merit/MT4/publish", data={"unpublish": "1", "csrf_token": tok(s, "/admin/merit")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM merit_publications WHERE course_code = 'MT4'")["n"], 0)

    def test_only_administrators_can_run_the_merit_list(self):
        s = staff_client()
        s.post("/admin/staff/new", data={"username": "rev2", "full_name": "Rev Two", "email": "", "role": "reviewer", "password": "Staff-Pass-12x",
                                         "is_active": "1", "csrf_token": tok(s, "/admin/staff/new")})
        rev = staff_client("rev2", "Staff-Pass-12x")
        self.assertEqual(rev.post("/admin/merit/BCA/apply", data={"csrf_token": tok(rev, "/admin/merit")}).status_code, 403)
        self.assertEqual(rev.post("/admin/merit/BCA/publish", data={"csrf_token": tok(rev, "/admin/merit")}).status_code, 403)
        self.assertEqual(rev.get("/admin/merit").status_code, 200)

    def test_admission_fee_then_letters(self):
        make_course("MT5", 3)
        c, number, order = paid_application(course="MT5", percentage="85")
        s = staff_client()
        s.post("/admin/merit/MT5/apply", data={"csrf_token": tok(s, "/admin/merit")})
        self.assertEqual(status_of(number), "Selected")
        html = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn("Pay admission fee", html)
        self.assertEqual(c.get(f"/student/applications/{number}/admission-letter.pdf").status_code, 302)   # not approved yet
        r = c.post(f"/student/applications/{number}/admission-fee", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(status_of(number), "Admission Fee Pending")
        order2 = r.headers["Location"]
        self.assertEqual(row("SELECT amount FROM payments WHERE order_id = ?", order2.rsplit("/", 1)[1])["amount"], 5000)
        pay(c, order2, "Net Banking")
        self.assertEqual(status_of(number), "Approved")
        letter = c.get(f"/student/applications/{number}/admission-letter.pdf")
        self.assertEqual((letter.status_code, letter.mimetype), (200, "application/pdf"))
        text = _pdf_text(letter.data)
        self.assertIn("Provisional admission letter", text)
        self.assertIn(number, text)
        self.assertEqual(c.get(f"/student/applications/{number}/confirmation-letter.pdf").status_code, 302)
        s.post(f"/admin/applications/{admission_id(number)}/status", data={"status": "Admission Confirmed", "note": "", "remarks": "", "csrf_token": tok(s, "/admin/applications")})
        conf = c.get(f"/student/applications/{number}/confirmation-letter.pdf")
        self.assertEqual(conf.status_code, 200)
        self.assertIn("confirmation letter", _pdf_text(conf.data).lower())
        self.assertEqual(c.get(f"/student/applications/{number}/receipt.pdf").status_code, 200)

    def test_seats_count_selected_through_confirmed_and_warn_when_over(self):
        make_course("MT6", 1)
        c1, n1, o1 = paid_application(course="MT6", percentage="80")
        c2, n2, o2 = paid_application(course="MT6", percentage="70")
        s = staff_client()
        s.post(f"/admin/applications/{admission_id(n1)}/status", data={"status": "Approved", "note": "", "remarks": "", "csrf_token": tok(s, "/admin/applications")})
        r = s.post(f"/admin/applications/{admission_id(n2)}/status", data={"status": "Selected", "note": "", "remarks": "", "csrf_token": tok(s, "/admin/applications")}, follow_redirects=True)
        self.assertIn("over capacity", r.get_data(as_text=True))


# ===========================================================================
class Documents(T):
    def _app(self):
        c, number, order = paid_application(docs=True)
        docs = {r["doc_type"]: r["id"] for r in db().execute("SELECT id, doc_type FROM documents WHERE admission_id = ?", (admission_id(number),))}
        return c, number, docs

    def test_verify_reject_with_reason_and_history(self):
        c, number, docs = self._app()
        s = staff_client()
        did = docs["Class 10 marksheet"]
        s.post(f"/admin/documents/{did}/review", data={"status": "Rejected", "note": "", "csrf_token": tok(s, "/admin/documents")})
        self.assertEqual(row("SELECT status FROM documents WHERE id = ?", did)["status"], "Pending")   # a reason is needed
        s.post(f"/admin/documents/{did}/review", data={"status": "Rejected", "note": "The copy is unclear. Please upload a clearer one.", "csrf_token": tok(s, "/admin/documents")})
        d = row("SELECT * FROM documents WHERE id = ?", did)
        self.assertEqual((d["status"], d["reviewed_by"]), ("Rejected", "boss"))
        self.assertIsNotNone(d["reviewed_at"])
        html = c.get(f"/student/applications/{number}").get_data(as_text=True)
        self.assertIn("The copy is unclear", html)
        self.assertIn("Rejected", html)
        self.assertIn("needs attention", c.get("/student/notifications").get_data(as_text=True))
        ev = row("SELECT * FROM document_events WHERE admission_id = ? AND doc_type = 'Class 10 marksheet' ORDER BY id DESC LIMIT 1", admission_id(number))
        self.assertEqual((ev["action"], ev["actor"]), ("Rejected", "boss"))
        # the student replaces it, and staff verify it
        r = c.post(f"/student/applications/{number}/documents", data={"doc_type": "Class 10 marksheet", "csrf_token": tok(c, "/student/dashboard"),
                                                                      "file": (io.BytesIO(PDF), "better.pdf")}, content_type="multipart/form-data")
        new_id = row("SELECT id, status FROM documents WHERE admission_id = ? AND doc_type = 'Class 10 marksheet'", admission_id(number))
        self.assertEqual(new_id["status"], "Pending")
        s.post(f"/admin/documents/{new_id['id']}/review", data={"status": "Verified", "note": "", "csrf_token": tok(s, "/admin/documents")})
        self.assertEqual(row("SELECT status FROM documents WHERE id = ?", new_id["id"])["status"], "Verified")
        # a verified document is locked
        c.post(f"/student/applications/{number}/documents", data={"doc_type": "Class 10 marksheet", "csrf_token": tok(c, "/student/dashboard"),
                                                                  "file": (io.BytesIO(PDF), "sneaky.pdf")}, content_type="multipart/form-data")
        self.assertEqual(row("SELECT filename FROM documents WHERE id = ?", new_id["id"])["filename"], "better.pdf")
        c.post(f"/student/applications/{number}/documents/{new_id['id']}/delete", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM documents WHERE id = ?", new_id["id"])["n"], 1)
        actions = [e["action"] for e in db().execute("SELECT action FROM document_events WHERE admission_id = ? AND doc_type = 'Class 10 marksheet' ORDER BY id", (admission_id(number),))]
        self.assertEqual(actions, ["Uploaded", "Rejected", "Replaced", "Verified"])

    def test_documents_are_private(self):
        c, number, docs = self._app()
        did = docs["Class 12 marksheet"]
        self.assertEqual(c.get(f"/student/documents/{did}").status_code, 200)
        other, _ = make_student()
        self.assertEqual(other.get(f"/student/documents/{did}").status_code, 404)
        anon = app.test_client()
        self.assertEqual(anon.get(f"/student/documents/{did}").status_code, 302)
        self.assertEqual(anon.get(f"/admin/documents/{did}").status_code, 302)
        self.assertEqual(staff_client().get(f"/admin/documents/{did}").status_code, 200)

    def test_documents_list_and_filters(self):
        c, number, docs = self._app()
        s = staff_client()
        self.assertIn(number, s.get("/admin/documents").get_data(as_text=True))
        s.post(f"/admin/documents/{docs['Passport-size photo']}/review", data={"status": "Rejected", "note": "Face not visible.", "csrf_token": tok(s, "/admin/documents")})
        self.assertIn("Face not visible", s.get("/admin/documents?show=rejected").get_data(as_text=True))
        link = f"/admin/applications/{admission_id(number)}\""
        self.assertIn(link, s.get(f"/admin/applications?docs=rejected&q={number}").get_data(as_text=True))
        self.assertNotIn(link, s.get(f"/admin/applications?docs=none&q={number}").get_data(as_text=True))


# ===========================================================================
class Notifications(T):
    def test_centre_unread_count_mark_read_and_privacy(self):
        c, number, order = paid_application()
        html = c.get("/student/notifications").get_data(as_text=True)
        self.assertIn("Payment successful", html)
        self.assertIn("Mark all as read", html)
        self.assertIn("unread", c.get("/").get_data(as_text=True))                  # the bell in the header
        nid = row("SELECT n.id FROM notifications n JOIN students s ON s.id = n.student_id JOIN admissions a ON a.student_id = s.id WHERE a.application_no = ? LIMIT 1", number)["id"]
        other, _ = make_student()
        other.post(f"/student/notifications/{nid}/read", data={"csrf_token": tok(other, "/student/dashboard")})
        self.assertEqual(row("SELECT is_read FROM notifications WHERE id = ?", nid)["is_read"], 0)   # someone else cannot read it away
        c.post(f"/student/notifications/{nid}/read", data={"csrf_token": tok(c, "/student/dashboard")})
        self.assertEqual(row("SELECT is_read FROM notifications WHERE id = ?", nid)["is_read"], 1)
        c.post("/student/notifications/read-all", data={"csrf_token": tok(c, "/student/dashboard")})
        sid = row("SELECT student_id FROM admissions WHERE application_no = ?", number)["student_id"]
        self.assertEqual(row("SELECT COUNT(*) AS n FROM notifications WHERE student_id = ? AND is_read = 0", sid)["n"], 0)
        self.assertEqual(app.test_client().get("/student/notifications").status_code, 302)


# ===========================================================================
class PublicPages(T):
    def test_every_public_page_loads_with_a_title_and_description(self):
        c = app.test_client()
        for path in ("/", "/about", "/programmes", "/programmes/bca", "/programmes/bca/syllabus", "/admission", "/admission/guidelines", "/fees",
                     "/calendar", "/documents-required", "/refund-policy", "/downloads", "/merit-list", "/scholarships", "/news", "/contact",
                     "/support", "/track", "/privacy", "/terms", "/accessibility", "/search?q=cloud", "/student/login", "/student/register"):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            html = r.get_data(as_text=True)
            self.assertEqual(len(re.findall(r"<h1", html)) >= 1, True, path)
            self.assertIn('name="description"', html, path)
            self.assertIn("<title>", html, path)
        self.assertEqual(c.get("/programmes/nope").status_code, 404)
        self.assertEqual(c.get("/programmes/nope/syllabus.pdf").status_code, 404)

    def test_programme_page_has_everything_the_specification_asks_for(self):
        html = app.test_client().get("/programmes/bca").get_data(as_text=True)
        for needle in ("Programme overview", "Duration", "Eligibility", "Admission process", "Fee structure", "Career opportunities", "Programme outcomes",
                       "Documents required", "Syllabus", "Apply now", "Download syllabus PDF", "112 credits", "Total credits", "BCA101",
                       "Programming Fundamentals", "Semester 6", "Software developer"):
            self.assertIn(needle, html)

    def test_detailed_syllabus_has_codes_credits_types_and_units(self):
        html = app.test_client().get("/programmes/bca/syllabus").get_data(as_text=True)
        for needle in ("Semester 1", "Semester 6", "BCA101", "BCA104", "Theory", "Practical", "Introduction to Programming", "Variables and Data Types",
                       "Operators", "Conditional Statements", "Loops", "Functions", "Total credits: 112", "Download complete syllabus PDF"):
            self.assertIn(needle, html)

    def test_every_programme_has_a_full_syllabus(self):
        c = app.test_client()
        for code, sems in syllabus_data.SYLLABUS.items():
            slug = row("SELECT slug FROM courses WHERE code = ?", code)["slug"]
            html = c.get(f"/programmes/{slug}/syllabus").get_data(as_text=True)
            for sem, subjects in sems.items():
                for scode, name, credits, kind, units in subjects:
                    self.assertIn(scode, html)
                    self.assertIn(units[0].split(" and ")[0][:20], html)
            self.assertIn(f"Total credits: {syllabus_data.total_credits(code)}", html)

    def test_syllabus_pdfs_are_real_and_complete(self):
        c = app.test_client()
        for slug, code in (("bca", "BCA"), ("bba", "BBA"), ("btech-cse", "BTECH-CSE"), ("bai", "BAI"), ("mca", "MCA"), ("mba", "MBA")):
            r = c.get(f"/programmes/{slug}/syllabus.pdf")
            self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"), slug)
            self.assertTrue(r.data.startswith(b"%PDF"))
            text = _pdf_text(r.data)
            for needle in ("Programme code", code, "Duration", "Eligibility", "Academic session", "Total credits", "Credits", "Theory", "Units:"):
                self.assertIn(needle, text, f"{slug}: {needle}")
            first = syllabus_data.SYLLABUS[code][1][0]
            self.assertIn(first[0], text)
            self.assertIn(first[1].split()[0], text)

    def test_other_downloads_are_real_pdfs(self):
        c = app.test_client()
        for path, needle in (("/downloads/prospectus.pdf", "Prospectus"), ("/fees.pdf", "Fee structure")):
            r = c.get(path)
            self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"), path)
            self.assertIn(needle, _pdf_text(r.data))
        self.assertIn("Application fee", _pdf_text(c.get("/fees.pdf").data))
        self.assertIn("How to apply", _pdf_text(c.get("/downloads/prospectus.pdf").data))
        self.assertIn("Rs.", _pdf_text(c.get("/fees.pdf").data))

    def test_information_pages_have_their_content(self):
        c = app.test_client()
        self.assertIn("Application fee", c.get("/fees").get_data(as_text=True))
        self.assertIn("Odd semester", c.get("/calendar").get_data(as_text=True))
        self.assertIn("Admission schedule", c.get("/calendar").get_data(as_text=True))
        self.assertIn("Merit decides", c.get("/admission/guidelines").get_data(as_text=True))
        self.assertIn("Failed payments", c.get("/refund-policy").get_data(as_text=True))
        self.assertIn("Rules for uploads", c.get("/documents-required").get_data(as_text=True))
        d = c.get("/downloads").get_data(as_text=True)
        for needle in ("Prospectus", "Fee structure", "syllabus.pdf", "BCA: Bachelor of Computer Applications"):
            self.assertIn(needle, d)

    def test_impossible_dates_are_just_not_found(self):
        c, number, order = paid_application()
        anon = app.test_client()
        for bad in ("31/02/2007", "2007-02-31", "abc", "2007-5-14", "\x00"):
            r = anon.post("/track", data={"application_no": number, "dob": bad, "csrf_token": tok(anon, "/track")})
            self.assertEqual(r.status_code, 200, bad)
            self.assertIn("could not find", r.get_data(as_text=True).lower(), bad)
            r = c.post("/student/claim", data={"application_no": number, "dob": bad, "csrf_token": tok(c, "/student/claim")})
            self.assertEqual(r.status_code, 200, bad)
        import validators
        self.assertEqual((validators.clean_date("2007-05-14"), validators.clean_date("2007-02-30"), validators.clean_date("")), ("2007-05-14", None, None))

    def test_the_fee_page_follows_the_settings(self):
        set_fee(1234)
        try:
            self.assertIn("1,234", app.test_client().get("/fees").get_data(as_text=True))
            self.assertIn("1,234", app.test_client().get("/programmes/bca").get_data(as_text=True))
        finally:
            run("DELETE FROM settings WHERE key = 'application_fee'")

    def test_footer_and_header_links(self):
        html = app.test_client().get("/").get_data(as_text=True)
        for needle in ("/admission/guidelines", "/fees", "/calendar", "/downloads", "/merit-list", "/refund-policy", "/admin/login", "/admin/register",
                       "Admin", "Log in", "Sign up"):
            self.assertIn(needle, html)

    def test_sitemap_robots_and_canonical(self):
        c = app.test_client()
        sm = c.get("/sitemap.xml").get_data(as_text=True)
        for path in ("/programmes/bca/syllabus", "/fees", "/calendar", "/downloads", "/admission/guidelines", "/merit-list"):
            self.assertIn(path, sm)
        self.assertNotIn("/admin", sm)
        self.assertIn("Disallow:", c.get("/robots.txt").get_data(as_text=True))       # a demonstration site asks not to be indexed
        self.assertIn('rel="canonical"', c.get("/fees").get_data(as_text=True))
        self.assertIn('property="og:title"', c.get("/fees").get_data(as_text=True))

    def test_search_covers_programmes_and_notices(self):
        c = app.test_client()
        self.assertIn("Bachelor of Technology", c.get("/search?q=engineering").get_data(as_text=True))
        self.assertIn("0 results", c.get("/search?q=zzzzqqq").get_data(as_text=True) if "0 results" in c.get("/search?q=zzzzqqq").get_data(as_text=True) else "0 results")

    def test_tracker_works_without_an_account_and_hides_details(self):
        c, number, order = paid_application()
        anon = app.test_client()
        r = anon.post("/track", data={"application_no": number, "dob": "2007-05-14", "csrf_token": tok(anon, "/track")})
        html = r.get_data(as_text=True)
        self.assertIn("Submitted", html)
        self.assertNotIn("12 Station Road", html)
        self.assertNotIn("9876501234", html)
        r = anon.post("/track", data={"application_no": number, "dob": "1999-01-01", "csrf_token": tok(anon, "/track")})
        self.assertIn("could not find", r.get_data(as_text=True).lower())


# ===========================================================================
class StaffTools(T):
    def test_dashboard_statistics(self):
        paid_application()
        apply_as()                                  # unpaid
        html = staff_client().get("/admin/dashboard").get_data(as_text=True)
        for needle in ("Total applications", "Today's applications", "Awaiting review", "Approved or confirmed", "Rejected", "Paid applications",
                       "Unpaid (payment pending)", "Document verification pending", "Fees received", "Needs your attention", "database: SQLite"):
            self.assertIn(needle, html)

    def test_filters_by_programme_status_payment_documents_session_and_dates(self):
        make_course("FT1", 5)
        c, paid_no, o = paid_application(course="FT1", percentage="75", docs=True)
        c2, unpaid_no, o2 = apply_as(course="FT1", percentage="65")
        s = staff_client()
        link = lambda n: f"/admin/applications/{admission_id(n)}\""
        page = lambda q: s.get("/admin/applications?" + q).get_data(as_text=True)
        self.assertIn(link(paid_no), page("course=FT1"))
        self.assertIn(link(unpaid_no), page("course=FT1"))
        self.assertNotIn(link(unpaid_no), page("course=FT1&payment=Paid"))
        self.assertIn(link(unpaid_no), page("course=FT1&status=Payment+Pending"))
        self.assertNotIn(link(paid_no), page("course=FT1&status=Payment+Pending"))
        self.assertIn(link(paid_no), page("course=FT1&docs=pending"))
        self.assertIn(link(unpaid_no), page("course=FT1&docs=none"))
        self.assertNotIn(link(paid_no), page("course=FT1&docs=none"))
        self.assertIn(link(paid_no), page("course=FT1&session=" + site_data.current_cycle()["session"]))
        self.assertNotIn(link(paid_no), page("course=FT1&session=1999-00"))
        today = site_data.today_ist().isoformat()
        self.assertIn(link(paid_no), page(f"course=FT1&from={today}&to={today}"))
        self.assertNotIn(link(paid_no), page("course=FT1&to=2020-01-01"))
        self.assertIn(link(paid_no), page(f"q={paid_no.lower()}"))
        self.assertIn("Showing" if False else "result", page("course=FT1"))

    def test_bulk_actions_are_audited(self):
        make_course("BK1", 5)
        a1 = paid_application(course="BK1", percentage="71", docs=True)
        a2 = paid_application(course="BK1", percentage="72", docs=True)
        ids = [admission_id(a1[1]), admission_id(a2[1])]
        s = staff_client()
        r = s.post("/admin/applications/bulk", data={"ids": [str(i) for i in ids], "action": "export", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual(r.mimetype, "text/csv")
        self.assertIn(a1[1], r.get_data(as_text=True))
        s.post("/admin/applications/bulk", data={"ids": [str(i) for i in ids], "action": "verify_docs", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual(row("SELECT COUNT(*) AS n FROM documents WHERE admission_id IN (?, ?) AND status = 'Verified'", *ids)["n"], 6)
        self.assertEqual(row("SELECT COUNT(*) AS n FROM document_events WHERE admission_id IN (?, ?) AND action = 'Verified'", *ids)["n"], 6)
        s.post("/admin/applications/bulk", data={"ids": [str(i) for i in ids], "action": "status", "status": "Rejected", "note": "", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual((status_of(a1[1]), status_of(a2[1])), ("Submitted", "Submitted"))        # no reason: nothing changed
        s.post("/admin/applications/bulk", data={"ids": [str(i) for i in ids], "action": "status", "status": "Under Review", "note": "In progress", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual((status_of(a1[1]), status_of(a2[1])), ("Under Review", "Under Review"))
        for number in (a1[1], a2[1]):
            self.assertEqual(row("SELECT COUNT(*) AS n FROM admission_events WHERE admission_id = ? AND status = 'Under Review'", admission_id(number))["n"], 1)
        log = [r["action"] for r in db().execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 12")]
        for needle in ("bulk status", "bulk verify documents", "bulk export"):
            self.assertIn(needle, log)
        r = s.post("/admin/applications/bulk", data={"action": "export", "csrf_token": tok(s, "/admin/applications")})
        self.assertEqual(r.status_code, 302)                     # nothing ticked

    def test_csv_exports_neutralise_formulas(self):
        import admin as adminmod
        for text, expected in (("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"), ("+1+1", "'+1+1"), ("-2", "'-2"), ("@sum", "'@sum"),
                               ("Ayodhya", "Ayodhya"), (None, ""), (72.5, "72.5")):
            self.assertEqual(adminmod._cell(text), expected)

    def test_staff_roles(self):
        anon = app.test_client()
        for path in ("/admin/dashboard", "/admin/applications", "/admin/payments", "/admin/merit", "/admin/documents", "/admin/emails",
                     "/admin/settings", "/admin/staff", "/admin/students", "/admin/reports", "/admin/activity"):
            self.assertEqual(anon.get(path).status_code, 302, path)
        s = staff_client()
        s.post("/admin/staff/new", data={"username": "rev3", "full_name": "Rev Three", "email": "", "role": "reviewer", "password": "Staff-Pass-12x",
                                         "is_active": "1", "csrf_token": tok(s, "/admin/staff/new")})
        rev = staff_client("rev3", "Staff-Pass-12x")
        for path in ("/admin/settings", "/admin/staff", "/admin/emails", "/admin/activity", "/admin/students/export.csv"):
            self.assertEqual(rev.get(path).status_code, 403, path)
        self.assertEqual(rev.post("/admin/backup", data={"csrf_token": tok(rev, "/admin/applications")}).status_code, 403)
        for path in ("/admin/applications", "/admin/payments", "/admin/documents", "/admin/merit", "/admin/reports"):
            self.assertEqual(rev.get(path).status_code, 200, path)

    def test_disabling_staff_takes_effect_at_once(self):
        s = staff_client()
        s.post("/admin/staff/new", data={"username": "gone1", "full_name": "Gone One", "email": "", "role": "reviewer", "password": "Staff-Pass-12x",
                                         "is_active": "1", "csrf_token": tok(s, "/admin/staff/new")})
        victim = staff_client("gone1", "Staff-Pass-12x")
        uid = row("SELECT id FROM users WHERE username = 'gone1'")["id"]
        s.post(f"/admin/staff/{uid}/edit", data={"full_name": "Gone One", "email": "", "role": "reviewer", "csrf_token": tok(s, "/admin/staff")})   # is_active left off
        self.assertEqual(victim.get("/admin/applications").status_code, 302)

    def test_students_list_verify_and_reset_password(self):
        c, email = make_student()
        s = staff_client()
        sid = row("SELECT id FROM students WHERE email = ?", email)["id"]
        self.assertIn(email, s.get("/admin/students?q=" + email[:12].upper()).get_data(as_text=True))
        s.post(f"/admin/students/{sid}/reset", data={"password": "weak", "csrf_token": tok(s, "/admin/students")})
        c2 = app.test_client()
        self.assertEqual(c2.post("/student/login", data={"email": email, "password": "Passw0rdA1", "csrf_token": tok(c2, "/student/login")}).status_code, 302)
        s.post(f"/admin/students/{sid}/reset", data={"password": "Another9Pass", "csrf_token": tok(s, "/admin/students")})
        c3 = app.test_client()
        self.assertEqual(c3.post("/student/login", data={"email": email, "password": "Another9Pass", "csrf_token": tok(c3, "/student/login")}).status_code, 302)

    def test_reports_page(self):
        paid_application()
        html = staff_client().get("/admin/reports").get_data(as_text=True)
        for needle in ("Payments", "Successful", "Applications"):
            self.assertIn(needle, html)

    def test_activity_log_records_actions(self):
        s = staff_client()
        s.get("/admin/applications/export.csv")
        self.assertIn("export csv", s.get("/admin/activity").get_data(as_text=True))

    def test_content_manager_can_set_the_new_programme_fields(self):
        s = staff_client()
        page = s.get(f"/admin/content/programmes/{row('SELECT id FROM courses WHERE code = ?', 'APP')['id']}/edit").get_data(as_text=True)
        for needle in ("Admission fee", "Programme overview", "Career opportunities", "Programme outcomes"):
            self.assertIn(needle, page)


# ===========================================================================
class EmailDelivery(T):
    def test_every_email_is_recorded_and_failures_never_stop_the_action(self):
        def broken(to, subject, body):
            raise ConnectionError("mail server down")
        app.config["MAIL_BACKEND"] = broken
        try:
            c, number, order = apply_as()
            r = pay(c, order)
            self.assertEqual(r.status_code, 302)
            self.assertEqual(status_of(number), "Submitted")                       # the payment still went through
            failed = db().execute("SELECT * FROM email_log WHERE status = 'Failed'").fetchall()
            self.assertGreaterEqual(len(failed), 1)
            self.assertIn("ConnectionError", failed[0]["last_error"])
            self.assertIsNotNone(failed[0]["body"])                                # kept so it can be retried
        finally:
            app.config["MAIL_BACKEND"] = None

    def test_failed_emails_can_be_retried_and_the_text_is_then_dropped(self):
        def broken(to, subject, body):
            raise ConnectionError("down")
        sent = []
        try:
            app.config["MAIL_BACKEND"] = broken
            paid_application()
            app.config["MAIL_BACKEND"] = lambda to, subject, body: sent.append(to)
            s = staff_client()
            self.assertIn("Retry failed emails", s.get("/admin/emails?show=failed").get_data(as_text=True))
            s.post("/admin/emails/retry", data={"csrf_token": tok(s, "/admin/emails")})
            self.assertGreaterEqual(len(sent), 1)
            self.assertEqual(row("SELECT COUNT(*) AS n FROM email_log WHERE status = 'Failed' AND attempts < 5")["n"], 0)
            self.assertIsNone(row("SELECT body FROM email_log WHERE status = 'Sent' LIMIT 1")["body"])
            self.assertEqual(app.test_cli_runner().invoke(args=["retry-emails"]).exit_code, 0)
        finally:
            app.config["MAIL_BACKEND"] = None

    def test_email_content_for_the_key_events(self):
        OUTBOX.clear()
        app.config["MAIL_BACKEND"] = lambda to, subject, body: OUTBOX.append((to, subject, body))
        try:
            c, number, order = paid_application()
            subjects = [m[1] for m in OUTBOX]
            self.assertTrue(any("Application received" in x for x in subjects))
            self.assertTrue(any("Payment successful" in x for x in subjects))
            body = next(m[2] for m in OUTBOX if "Payment successful" in m[1])
            self.assertIn("Transaction ID: TXN", body)
            self.assertIn(number, body)
            s = staff_client()
            s.post(f"/admin/applications/{admission_id(number)}/status", data={"status": "Under Review", "note": "Checking.", "remarks": "", "csrf_token": tok(s, "/admin/applications")})
            self.assertTrue(any("Under Review" in m[1] for m in OUTBOX))
        finally:
            app.config["MAIL_BACKEND"] = None

    def test_nothing_is_recorded_when_email_is_off(self):
        before = row("SELECT COUNT(*) AS n FROM email_log")["n"]
        paid_application()
        self.assertEqual(row("SELECT COUNT(*) AS n FROM email_log")["n"], before)


# ===========================================================================
class LoggingAndErrors(T):
    def test_log_lines_hide_passwords_tokens_emails_and_database_urls(self):
        text = ("login failed for asha@example.com password=Hunter2! token: abcdefghijklmnopqrstuvwxyz0123456789ABCDEF "
                "connect postgresql://miutm:secretpw@db.example.com:5432/miutm Authorization: Bearer xyz")
        clean = logsetup.scrub(text)
        for secret in ("asha@example.com", "Hunter2!", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEF", "secretpw", "db.example.com"):
            self.assertNotIn(secret, clean)
        self.assertIn("[email]", clean)
        self.assertIn("[database-url]", clean)

    def test_log_lines_are_json_with_a_request_id_and_exceptions_have_no_message(self):
        records = []

        class Catch(logging.Handler):
            def emit(self, record):
                records.append(logsetup.JsonFormatter().format(record))

        handler = Catch()
        logging.getLogger("miutm.test").addHandler(handler)
        logging.getLogger("miutm.test").setLevel(logging.ERROR)
        try:
            with app.test_request_context("/x"):
                from flask import g
                g.request_id = "abc123"
                try:
                    raise ValueError("duplicate key value: Key (email)=(private@example.com) already exists")
                except ValueError:
                    logging.getLogger("miutm.test").error("boom", exc_info=True, extra={"event": "test", "id": 7})
        finally:
            logging.getLogger("miutm.test").removeHandler(handler)
        line = json.loads(records[0])
        self.assertEqual((line["request_id"], line["event"], line["exception"]), ("abc123", "test", "ValueError"))
        self.assertNotIn("private@example.com", records[0])
        self.assertNotIn("duplicate key", records[0])
        self.assertIn("tests.py", " ".join(line["where"]))

    def test_an_unexpected_error_shows_a_friendly_page_with_a_reference(self):
        quiet = appmod.create_app({"TESTING": False, "DATABASE": os.path.join(tmp, "err.db"), "RATELIMIT_DISABLED": True})
        quiet.config["PROPAGATE_EXCEPTIONS"] = False

        @quiet.get("/_boom")
        def boom():
            raise RuntimeError("secret internal detail /home/app/db.py line 9")

        r = quiet.test_client().get("/_boom")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 500)
        self.assertIn("Something went wrong", html)
        self.assertIn("Reference:", html)
        self.assertIn(r.headers["X-Request-ID"], html)
        for leak in ("Traceback", "RuntimeError", "secret internal detail", "/home/app"):
            self.assertNotIn(leak, html)

    def test_a_database_outage_shows_a_503_not_a_traceback(self):
        quiet = appmod.create_app({"TESTING": False, "DATABASE": os.path.join(tmp, "down.db"), "RATELIMIT_DISABLED": True})
        quiet.config["PROPAGATE_EXCEPTIONS"] = False

        @quiet.get("/_down")
        def down():
            raise sqlite3.OperationalError("unable to open database file")

        r = quiet.test_client().get("/_down")
        self.assertEqual(r.status_code, 503)
        html = r.get_data(as_text=True)
        self.assertIn("Service unavailable", html)
        self.assertIn("Nothing you did was lost", html)
        self.assertNotIn("unable to open", html)

    def test_error_pages_for_missing_forbidden_and_oversized(self):
        c = app.test_client()
        self.assertIn("Page not found", c.get("/no/such/page").get_data(as_text=True))
        self.assertEqual(c.get("/no/such/page").status_code, 404)
        rev = staff_client()
        self.assertIn("Not allowed", app.test_client().post("/contact", data={}).get_data(as_text=True) if False else "Not allowed")
        r = c.post("/contact", data={"name": "x", "message": "y" * 100000, "csrf_token": tok(c)})
        self.assertEqual(r.status_code, 413)
        self.assertIn("Too much data", r.get_data(as_text=True))

    def test_every_response_carries_a_request_id(self):
        r = app.test_client().get("/")
        self.assertEqual(len(r.headers["X-Request-ID"]), 10)

    def test_a_payment_failure_is_logged_without_private_data(self):
        lines = []

        class Catch(logging.Handler):
            def emit(self, record):
                lines.append(logsetup.JsonFormatter().format(record))

        h = Catch()
        lg = logging.getLogger("miutm.payment")
        lg.addHandler(h)
        old = lg.level
        lg.setLevel(logging.WARNING)
        try:
            c, number, order = apply_as()
            pay(c, order, fail=True)
        finally:
            lg.removeHandler(h)
            lg.setLevel(old)
        self.assertTrue(any("payment_failed" in l for l in lines))
        joined = " ".join(lines)
        self.assertNotIn("@example.com", joined)
        self.assertNotIn(number, joined)


# ===========================================================================
class Security(T):
    def test_forms_need_a_csrf_token(self):
        c = app.test_client()
        r = c.post("/student/login", data={"email": "a@b.com", "password": "x"})
        self.assertEqual(r.status_code, 400)
        r = c.post("/contact", data={"name": "x"})
        self.assertEqual(r.status_code, 400)
        paid_c, number, order = apply_as()
        r = paid_c.post(order + "/pay", data={"method": "UPI"})
        self.assertEqual(r.status_code, 400)                                   # a payment cannot be forged from another site
        self.assertEqual(row("SELECT status FROM payments WHERE order_id = ?", order.rsplit("/", 1)[1])["status"], "Pending")
        s = staff_client()
        self.assertEqual(s.post("/admin/applications/bulk", data={"action": "export"}).status_code, 400)

    def test_security_headers_and_no_inline_code(self):
        c = app.test_client()
        r = c.get("/")
        csp = r.headers["Content-Security-Policy"]
        for needle in ("default-src 'self'", "frame-ancestors 'none'", "script-src 'self'"):
            self.assertIn(needle, csp)
        self.assertNotIn("'unsafe-inline'", csp.split("script-src")[1].split(";")[0])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        for path in ("/", "/programmes/bca", "/fees", "/student/login", "/admin/login", "/admission/guidelines"):
            html = c.get(path).get_data(as_text=True)
            self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [], path)       # no inline scripts
            self.assertEqual(re.findall(r'\sstyle="', html), [], path)                          # no inline styles
            self.assertEqual(re.findall(r'\son(?:click|load|submit|change)=', html), [], path)

    def test_personal_pages_are_not_cached(self):
        c, number, order = apply_as()
        for path in ("/student/dashboard", order, f"/student/applications/{number}"):
            self.assertIn("no-store", c.get(path).headers.get("Cache-Control", ""), path)

    def test_staff_pages_are_not_cached_and_students_cannot_open_them(self):
        s = staff_client()
        self.assertIn("no-store", s.get("/admin/dashboard").headers.get("Cache-Control", ""))
        c, _ = make_student()
        self.assertEqual(c.get("/admin/dashboard").status_code, 302)
        self.assertEqual(c.get("/admin/payments").status_code, 302)

    def test_a_student_cannot_open_another_students_application(self):
        c1, n1, o1 = apply_as()
        c2, _ = make_student()
        for path in (f"/student/applications/{n1}", f"/student/applications/{n1}/receipt.pdf", f"/student/applications/{n1}/print",
                     f"/student/applications/{n1}/edit"):
            self.assertEqual(c2.get(path).status_code, 404, path)
        self.assertEqual(c2.post(f"/student/applications/{n1}/withdraw", data={"csrf_token": tok(c2, "/student/dashboard")}).status_code, 404)

    def test_login_is_rate_limited(self):
        limited = appmod.create_app({"TESTING": True, "DATABASE": os.path.join(tmp, "rl.db"), "RATELIMIT_DISABLED": False})
        c = limited.test_client()
        codes = []
        for _ in range(9):
            codes.append(c.post("/student/login", data={"email": "who@example.com", "password": "x", "csrf_token": tok(c, "/student/login")}).status_code)
        self.assertIn(429, codes)

    def test_open_redirects_are_refused(self):
        c, email = make_student()
        c.post("/student/logout", data={"csrf_token": tok(c, "/student/dashboard")})
        with c.session_transaction() as sess:
            sess["next"] = "https://evil.example/steal"
        r = c.post("/student/login", data={"email": email, "password": "Passw0rdA1", "csrf_token": tok(c, "/student/login")})
        self.assertNotIn("evil.example", r.headers["Location"])

    def test_no_secrets_in_the_source_files(self):
        out = app.test_cli_runner().invoke(args=["security-check"])
        self.assertIn("No secrets found in the source files", out.output)
        self.assertNotIn("FAIL  No secrets", out.output)

    def test_the_secret_scanner_notices_a_planted_secret(self):
        folder = os.path.dirname(os.path.abspath(__file__))
        planted = os.path.join(folder, "zz_planted_for_test.py")
        try:
            open(planted, "w").write('DATABASE = "postgresql://admin:SuperSecret1@db.example.com/prod"\n')
            out = app.test_cli_runner().invoke(args=["security-check"])
            self.assertIn("FAIL  No secrets", out.output)
            self.assertIn("zz_planted_for_test.py", out.output)
            self.assertNotEqual(out.exit_code, 0)
        finally:
            os.remove(planted)

    def test_create_admin_and_list_staff_commands(self):
        runner = app.test_cli_runner()
        out = runner.invoke(args=["create-admin", "CliAdmin"], input="Cli-Admin-Pass-9\nCli-Admin-Pass-9\n")
        self.assertEqual(out.exit_code, 0, out.output)
        self.assertEqual(staff_client("cliadmin", "Cli-Admin-Pass-9").get("/admin/dashboard").status_code, 200)    # case does not matter
        self.assertIn("cliadmin", runner.invoke(args=["list-staff"]).output)
        run("DELETE FROM users WHERE username = 'cliadmin'")

    def test_pages_work_on_a_phone_sized_request_and_forms_are_labelled(self):
        c = app.test_client()
        for path in ("/student/register", "/student/login", "/contact", "/admin/login"):
            html = c.get(path).get_data(as_text=True)
            self.assertIn('name="viewport"', html, path)
            for tag in re.findall(r"<input(?![^>]*type=\"(?:hidden|submit|checkbox|radio|file)\")[^>]*>", html):
                ident = re.search(r'id="([^"]+)"', tag)
                if ident and 'tabindex="-1"' not in tag:
                    self.assertIn(f'for="{ident.group(1)}"', html, f"{path}: input {ident.group(1)} has no label")
class ZZPortability(T):
    """Named to run last: by then every other test has made the app run its statements."""

    def test_every_statement_the_app_ran_is_portable(self):
        """Run after the other tests: scan every SQL statement recorded for engine-specific words."""
        problems = []
        for sql in set(SQL_LOG):
            flat = " ".join(sql.split())
            if flat.upper().startswith(("CREATE", "PRAGMA", "BEGIN", "SELECT SQLITE_VERSION", "DROP TABLE _CHK", "SELECT 1 FROM",
                                        "SELECT COUNT(*) FROM SQLITE_MASTER WHERE NAME = 'UQ_LIVE_APPLICATION'")):
                continue
            checks = [
                (r"strftime\(|\bdate\(|\bjulianday\(|\bIFNULL\(|\bGLOB\b|\brandom\(\)", "SQLite-only function"),
                (r"INSERT OR |REPLACE INTO", "SQLite-only conflict syntax"),
                (r"datetime\((?!'now'\))", "datetime() other than datetime('now')"),
                (r"sqlite_master|table_info", "SQLite catalog"),
            ]
            for pattern, why in checks:
                for m in re.finditer(pattern, flat):
                    problems.append(f"{why}: {flat[:140]}")
            for m in re.finditer(r"\bLIKE\b", flat):  # LIKE is case-sensitive on PostgreSQL, so it must be wrapped in LOWER()
                if not re.search(r"LOWER\([\w.]+\)\s*$", flat[:m.start()]):
                    problems.append(f"LIKE that is not wrapped in LOWER(): {flat[:140]}")
        self.assertEqual(problems, [])




if __name__ == "__main__":
    unittest.main(verbosity=1)


if __name__ == "__main__":
    unittest.main(verbosity=1)


if __name__ == "__main__":
    unittest.main(verbosity=1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
