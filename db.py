"""
db.py - database access for SQLite (local development and tests) and PostgreSQL (production).

Set DATABASE_URL to use PostgreSQL. Without it the app uses the SQLite file in DATABASE_PATH.
The rest of the app writes ordinary SQL with ? placeholders; for PostgreSQL this module rewrites the few
engine differences (placeholders, now(), RETURNING id), returns rows that behave like sqlite3.Row, and
returns dates and times as text so the pages see the same values on both engines.
"""
import logging
import os
import re
import secrets
import sqlite3
import string

from flask import current_app, g
from werkzeug.security import generate_password_hash

import schema
import seed_data

try:  # PostgreSQL driver: only needed in production
    import psycopg2
    import psycopg2.extensions as _ext
    import psycopg2.pool
except ImportError:  # pragma: no cover
    psycopg2 = None

log = logging.getLogger("miutm.db")

IntegrityError = (sqlite3.IntegrityError,) + ((psycopg2.IntegrityError,) if psycopg2 else ())
OperationalError = (sqlite3.OperationalError,) + ((psycopg2.OperationalError,) if psycopg2 else ())

if psycopg2:
    # DATE / TIMESTAMP come back as text and NUMERIC as float, exactly as SQLite returned them.
    _ext.register_type(_ext.new_type((1082, 1114, 1184), "TIMETEXT", lambda v, cur: v))
    _ext.register_type(_ext.new_type((1700,), "NUMFLOAT", lambda v, cur: None if v is None else float(v)))

_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)


class Row:
    """A result row that works like sqlite3.Row: row[0], row['name'], dict(row), and row.name in templates."""
    __slots__ = ("_idx", "_vals")

    def __init__(self, idx, vals):
        self._idx, self._vals = idx, vals

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._vals[key]
        return self._vals[self._idx[key]]

    def keys(self):
        return list(self._idx)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class PgResult:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid, self.rowcount = cur, lastrowid, cur.rowcount
        self._idx = {d[0]: i for i, d in enumerate(cur.description)} if cur.description else {}

    @property
    def columns(self):
        return list(self._idx)

    def fetchone(self):
        r = self._cur.fetchone()
        return None if r is None else Row(self._idx, r)

    def fetchall(self):
        return [Row(self._idx, r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PgConn:
    """The few sqlite3 connection methods the app uses, on top of a psycopg2 connection."""

    def __init__(self, raw, pool=None):
        self.raw, self._pool = raw, pool

    @staticmethod
    def safe(params):
        """PostgreSQL refuses text containing a NUL character; SQLite does not. Drop them so a stray one in a
        form field cannot turn into a server error."""
        return tuple(p.replace("\x00", "") if isinstance(p, str) else p for p in params)

    @staticmethod
    def translate(sql, has_params):
        sql = sql.replace("datetime('now')", "(now() AT TIME ZONE 'utc')")
        if has_params:
            sql = sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql, params=(), returning=True):
        params = self.safe(tuple(params or ()))
        sql = self.translate(sql, bool(params))
        want_id = False
        m = _INSERT.match(sql)
        if (returning and m and m.group(1).lower() not in schema.TABLES_WITHOUT_ID
                and "returning" not in sql.lower() and "on conflict" not in sql.lower()):
            sql, want_id = sql.rstrip().rstrip(";") + " RETURNING id", True
        cur = self.raw.cursor()
        try:
            cur.execute(sql, params or None)
        except psycopg2.Error as exc:  # logged without the values (they can be private)
            log.error("database statement failed", extra={"event": "db_error", "sqlstate": getattr(exc, "pgcode", None),
                                                          "error": type(exc).__name__, "statement": sql[:80]})
            raise
        last = cur.fetchone()[0] if want_id else None
        return PgResult(cur, last)

    def executemany(self, sql, seq):
        cur = self.raw.cursor()
        cur.executemany(self.translate(sql, True), [self.safe(tuple(row)) for row in seq])
        return cur

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        try:
            self.raw.rollback()
        except Exception:  # connection already gone
            pass
        if self._pool is not None:
            self._pool.putconn(self.raw, close=bool(self.raw.closed))
        else:
            self.raw.close()


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def is_postgres(app=None):
    return bool((app or current_app).config.get("DATABASE_URL"))


def _pool(app):
    pool = app.extensions.get("pgpool")
    if pool is None:  # created lazily, so each gunicorn worker gets its own after forking
        if psycopg2 is None:
            raise RuntimeError("DATABASE_URL is set but psycopg2 is not installed. Add psycopg2-binary to requirements.txt.")
        pool = psycopg2.pool.ThreadedConnectionPool(
            1, int(os.environ.get("DB_POOL_MAX", "10")), app.config["DATABASE_URL"], connect_timeout=10,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
        app.extensions["pgpool"] = pool
    return pool


def _sqlite(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        app = current_app
        if is_postgres(app):
            pool = _pool(app)
            raw = pool.getconn()
            if raw.closed:  # the server dropped an idle connection
                pool.putconn(raw, close=True)
                raw = pool.getconn()
            g.db = PgConn(raw, pool)
        else:
            g.db = _sqlite(app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def connect_standalone(app):
    """A direct connection for set-up and maintenance commands (outside a request)."""
    if is_postgres(app):
        if psycopg2 is None:
            raise RuntimeError("DATABASE_URL is set but psycopg2 is not installed.")
        return PgConn(psycopg2.connect(app.config["DATABASE_URL"], connect_timeout=10))
    folder = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(folder, exist_ok=True)
    return _sqlite(app.config["DATABASE"])


# ---------------------------------------------------------------------------
# Schema, migrations and starter data
# ---------------------------------------------------------------------------
def columns(conn, table, postgres):
    if postgres:
        rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ? "
                            "AND table_schema = current_schema()", (table,)).fetchall()
        return {r[0] for r in rows}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def add_column(conn, table, column, ddl, postgres):
    if column not in columns(conn, table, postgres):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {schema.render(ddl, postgres)}")


def _migration_columns(conn, pg):
    """Columns added over the versions. A fresh database already has them all."""
    ac = lambda t, c, d: add_column(conn, t, c, d, pg)
    ac("users", "full_name", "TEXT NOT NULL DEFAULT ''")
    ac("users", "email", "TEXT")
    ac("users", "role", "TEXT NOT NULL DEFAULT 'admin'")
    ac("users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    ac("users", "approved", "INTEGER NOT NULL DEFAULT 1")
    ac("students", "email_verified", "INTEGER NOT NULL DEFAULT 0")
    ac("courses", "is_published", "INTEGER NOT NULL DEFAULT 1")
    ac("courses", "admission_fee", "INTEGER NOT NULL DEFAULT 0")
    ac("courses", "overview", "TEXT NOT NULL DEFAULT ''")
    ac("courses", "careers", "TEXT NOT NULL DEFAULT ''")
    ac("courses", "outcomes", "TEXT NOT NULL DEFAULT ''")
    ac("faculty", "is_published", "INTEGER NOT NULL DEFAULT 1")
    ac("contact_messages", "reply", "TEXT")
    ac("contact_messages", "replied_at", "{TS}")
    ac("admissions", "student_id", "INTEGER")
    ac("admissions", "session", "TEXT")
    ac("admissions", "payment_status", "TEXT NOT NULL DEFAULT 'Unpaid'")
    ac("admissions", "merit_score", "{NUM}")
    ac("admissions", "merit_rank", "INTEGER")
    ac("admissions", "rejection_reason", "TEXT")
    ac("admissions", "submitted_at", "{TS}")
    ac("admission_events", "previous_status", "TEXT")
    ac("admission_events", "changed_by", "TEXT")
    ac("documents", "reviewed_by", "TEXT")
    ac("documents", "reviewed_at", "{TS}")


def legacy_fixups(conn):
    """Bring rows written by version 4 (and earlier) in line with the version 5 vocabulary. Safe to repeat."""
    import site_data
    for old, new in (("Pending", "Submitted"), ("Enrolled", "Admission Confirmed")):
        conn.execute("UPDATE admissions SET status = ?, payment_status = 'Waived' WHERE status = ?", (new, old))
        conn.execute("UPDATE admission_events SET status = ? WHERE status = ?", (new, old))
    conn.execute("UPDATE admissions SET payment_status = 'Waived' WHERE payment_status = 'Unpaid' "
                 "AND status NOT IN ('Payment Pending', 'Cancelled')")
    conn.execute("UPDATE documents SET status = 'Pending' WHERE status = 'Uploaded'")
    conn.execute("UPDATE admissions SET session = ? WHERE session IS NULL", (site_data.CYCLE["session"],))
    conn.execute("UPDATE admissions SET submitted_at = created_at WHERE submitted_at IS NULL AND status <> 'Payment Pending'")


MIGRATIONS = [
    (1, "add columns introduced in versions 2 to 5", lambda conn, pg: _migration_columns(conn, pg)),
    (2, "rename version 4 statuses and fill in sessions", lambda conn, pg: legacy_fixups(conn)),
    (3, "existing students count as verified", lambda conn, pg: conn.execute("UPDATE students SET email_verified = 1")),
]


def run_migrations(conn, postgres, commit=True):
    """Apply the migrations not yet recorded. With commit=False the caller owns the transaction, so the whole
    start-up is one all-or-nothing step (and the lock taken at its start is held until the end)."""
    done = {r[0] for r in conn.execute("SELECT id FROM schema_migrations").fetchall()}
    for mid, name, fn in MIGRATIONS:
        if mid in done:
            continue
        fn(conn, postgres)
        conn.execute("INSERT INTO schema_migrations (id, name) VALUES (?, ?)", (mid, name))
        if commit:
            conn.commit()
        log.info("migration applied", extra={"event": "migration", "id": mid})


def _random_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def seed(conn):
    """Starter content, added only to tables that are empty."""
    import syllabus_data
    count = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    if count("courses") == 0:
        conn.executemany(
            """INSERT INTO courses (code, slug, name, level, school, duration, eligibility, min_percent, accepts,
               audience, fee, fee_period, seats, summary, topics, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [c + (i,) for i, c in enumerate(seed_data.COURSES)])
    for code, info in syllabus_data.PROGRAMME_INFO.items():  # richer programme text, only where still empty
        conn.execute("UPDATE courses SET overview = ?, careers = ?, outcomes = ?, admission_fee = ? "
                     "WHERE code = ? AND overview = ''",
                     (info["overview"], "\n".join(info["careers"]), "\n".join(info["outcomes"]), info["admission_fee"], code))
    if count("subjects") == 0:
        for code, semesters in syllabus_data.SYLLABUS.items():
            for sem, subjects in semesters.items():
                for order, (scode, sname, credits, kind, units) in enumerate(subjects):
                    cur = conn.execute("INSERT INTO subjects (course_code, semester, code, name, credits, kind, sort_order) "
                                       "VALUES (?,?,?,?,?,?,?)", (code, sem, scode, sname, credits, kind, order))
                    conn.executemany("INSERT INTO subject_units (subject_id, unit_no, title) VALUES (?,?,?)",
                                     [(cur.lastrowid, n, t) for n, t in enumerate(units, 1)])
    if count("notices") == 0:
        conn.executemany("INSERT INTO notices (title, category, body, published_on) VALUES (?,?,?,?)", seed_data.NOTICES)
    if count("faqs") == 0:
        conn.executemany("INSERT INTO faqs (question, answer, sort_order) VALUES (?,?,?)", seed_data.FAQS)
    if count("events") == 0:
        conn.executemany("INSERT INTO events (title, description, location, starts_on, ends_on) VALUES (?,?,?,?,?)",
                         seed_data.EVENTS)
    if count("faculty") == 0:
        conn.executemany("INSERT INTO faculty (name, designation, school, specialization) VALUES (?,?,?,?)",
                         seed_data.FACULTY)


def init_db(app):
    """Create what is missing, upgrade what is old, add starter data, make sure an administrator exists.
    Safe to run on every start, and safe if several processes start at once."""
    postgres = is_postgres(app)
    conn = connect_standalone(app)
    try:
        if postgres:
            conn.execute("SELECT pg_advisory_lock(727001)")  # one process at a time past this point
        else:
            conn.execute("PRAGMA journal_mode = WAL")
        for stmt in schema.TABLES:
            conn.execute(schema.render(stmt, postgres))
        conn.commit()
        if not postgres:
            conn.execute("BEGIN IMMEDIATE")
        run_migrations(conn, postgres, commit=False)
        for stmt in schema.INDEXES:
            conn.execute(schema.render(stmt, postgres))
        seed(conn)
        first_admin = None
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            username = (os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin").lower()
            password = os.environ.get("ADMIN_PASSWORD", "")
            generated = not password
            if generated:
                password = _random_password()
            conn.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                         (username, generate_password_hash(password), "Administrator"))
            first_admin = (username, password) if generated else None
        conn.commit()
        if first_admin:  # printed once, and only after it is safely stored; only the hash is kept
            print("=" * 64)
            print(" First run: administrator account created")
            print(f"   username: {first_admin[0]}")
            print(f"   password: {first_admin[1]}")
            print(" Save this now. It will not be shown again.")
            print(" Lost it? Run:  flask --app app create-admin " + first_admin[0])
            print(" Tip: set ADMIN_USERNAME / ADMIN_PASSWORD env vars to choose your own.")
            print("=" * 64)
    finally:
        if postgres:
            try:
                conn.rollback()
                conn.execute("SELECT pg_advisory_unlock(727001)")
                conn.commit()
            except Exception:  # connection lost; the lock goes with it
                pass
        conn.close()


def like_pattern(term):
    """Lower-cased, escaped pattern for  LOWER(column) LIKE ? ESCAPE '\\'  (case-insensitive on both engines)."""
    return "%" + term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
