"""
db.py - SQLite access, schema and starter data.

Unlike the first version, nothing here ever drops a table. `init_db()` only creates
what is missing and seeds starter content when a table is empty, so it is safe to
run on every start.
"""
import os
import secrets
import sqlite3
import string

from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
-- Staff accounts (admins and reviewers)
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    email         TEXT,
    role          TEXT NOT NULL DEFAULT 'admin',
    is_active     INTEGER NOT NULL DEFAULT 1,
    approved      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login    TEXT
);

-- Student accounts
CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    phone         TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    level       TEXT NOT NULL,
    school      TEXT NOT NULL,
    duration    TEXT NOT NULL,
    eligibility TEXT NOT NULL,
    min_percent INTEGER NOT NULL DEFAULT 0,
    accepts     TEXT NOT NULL,
    audience    TEXT NOT NULL,
    fee         INTEGER NOT NULL,
    fee_period  TEXT NOT NULL,
    seats       INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    topics      TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_published INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS admissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_no TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    father_name    TEXT NOT NULL,
    mother_name    TEXT NOT NULL,
    gender         TEXT NOT NULL,
    dob            TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone          TEXT NOT NULL,
    category       TEXT,
    nationality    TEXT NOT NULL DEFAULT 'Indian',
    qualification  TEXT NOT NULL,
    percentage     REAL NOT NULL,
    course_code    TEXT NOT NULL,
    course_name    TEXT NOT NULL,
    address        TEXT NOT NULL,
    city           TEXT NOT NULL,
    state          TEXT NOT NULL,
    pincode        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'Pending',
    remarks        TEXT,
    student_id     INTEGER REFERENCES students(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_admissions_status  ON admissions(status);
CREATE INDEX IF NOT EXISTS idx_admissions_email   ON admissions(email);
CREATE INDEX IF NOT EXISTS idx_admissions_created ON admissions(created_at);

-- Uploaded files are kept inside the database so one backup file holds everything.
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE,
    doc_type     TEXT NOT NULL,
    filename     TEXT NOT NULL,
    mime         TEXT NOT NULL,
    size         INTEGER NOT NULL,
    data         BLOB NOT NULL,
    status       TEXT NOT NULL DEFAULT 'Uploaded',
    note         TEXT,
    uploaded_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (admission_id, doc_type)
);

-- What the applicant sees on the tracking page.
CREATE TABLE IF NOT EXISTS admission_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE,
    status       TEXT NOT NULL,
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contact_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    phone      TEXT,
    department TEXT NOT NULL,
    subject    TEXT NOT NULL,
    message    TEXT NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    reply      TEXT,
    replied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL,
    body         TEXT NOT NULL,
    published_on TEXT NOT NULL,
    is_published INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS faculty (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    designation    TEXT NOT NULL,
    school         TEXT NOT NULL,
    specialization TEXT NOT NULL,
    is_published   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    location     TEXT NOT NULL DEFAULT '',
    starts_on    TEXT NOT NULL,
    ends_on      TEXT,
    is_published INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS faqs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    is_published INTEGER NOT NULL DEFAULT 1
);

-- Grievance and help-desk tickets
CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_no  TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    phone      TEXT,
    category   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    message    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'Open',
    response   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- An application the student is still filling in (one per student), and its uploaded files
CREATE TABLE IF NOT EXISTS drafts (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS draft_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    doc_type    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    data        BLOB NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, doc_type)
);

-- Settings that administrators change from the staff area (dates, contact details)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Who did what, and when
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor      TEXT NOT NULL,
    role       TEXT NOT NULL,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# code, slug, name, level, school, duration, eligibility, min_percent, accepts, audience,
# fee, fee_period, seats, summary, topics
COURSES = [
    ("BCA", "bca", "Bachelor of Computer Applications", "Undergraduate",
     "School of Computing Sciences", "3 years",
     "12th with Mathematics or Computer Science, at least 50% marks.", 50,
     "12th (Intermediate)", "s12m", 95000, "per year", 120,
     "Programming, databases, web development and software projects, with AI and "
     "cybersecurity fundamentals in the later semesters.",
     "Programming,Database systems,Web development,Cloud computing,Artificial intelligence,"
     "Cybersecurity basics,Major project"),
    ("BBA", "bba", "Bachelor of Business Administration", "Undergraduate",
     "School of Management Studies", "3 years",
     "12th in any stream, at least 50% marks.", 50,
     "12th (Intermediate)", "s12m s12o", 105000, "per year", 120,
     "Business fundamentals, finance, marketing and communication for students who want to "
     "lead teams or start a venture.",
     "Management principles,Financial accounting,Marketing,Business communication,"
     "Entrepreneurship,Corporate strategy"),
    ("BTECH-CSE", "btech-cse", "Bachelor of Technology (Computer Science & Engineering)",
     "Undergraduate", "School of Engineering & Applied Technology", "4 years",
     "12th with Physics, Chemistry and Mathematics, at least 60% marks.", 60,
     "12th (Intermediate)", "s12m", 185000, "per year", 180,
     "A four-year engineering degree in computer science covering systems, software, "
     "AI and security.",
     "Data structures and algorithms,Machine learning,Cybersecurity,Full-stack development,"
     "Cloud computing,Data science,Distributed systems,Computer architecture"),
    ("BAI", "bai", "Bachelor of Artificial Intelligence", "Undergraduate",
     "School of Artificial Intelligence", "4 years",
     "12th with Physics, Chemistry and Mathematics, or with Computer Science, "
     "at least 55% marks.", 55,
     "12th (Intermediate)", "s12m", 165000, "per year", 120,
     "Machine learning from first principles to deployment, with Python as the working language.",
     "Machine learning,Deep learning,Generative AI,Natural language processing,Computer vision,"
     "Robotics,Python programming,Data science,Model deployment"),
    ("MCA", "mca", "Master of Computer Applications", "Postgraduate",
     "School of Computing Sciences", "2 years",
     "Bachelor's degree in computer applications or computer science, at least 55% marks.", 55,
     "Bachelor's degree,Master's degree", "gcs", 110000, "per year", 60,
     "Advanced software engineering for graduates, with enterprise systems, cloud and AI.",
     "Enterprise software design,Artificial intelligence,Cybersecurity,Full-stack development,"
     "Big data analytics,DevOps,Cloud-native applications"),
    ("MBA", "mba", "Master of Business Administration", "Postgraduate",
     "School of Management Studies", "2 years",
     "Bachelor's degree in any discipline, at least 50% marks, and a valid national "
     "entrance test score.", 50,
     "Bachelor's degree,Master's degree", "gcs gany", 145000, "per year", 90,
     "Management for graduates from any discipline, with finance, marketing, people and "
     "analytics tracks.",
     "Operations,Human resources,Marketing analytics,Corporate governance,Finance,Strategy"),
    ("DCSEH", "dcseh", "Diploma in Cyber Security & Ethical Hacking", "Diploma",
     "School of Cyber Security", "1 year",
     "12th or equivalent from any recognised board.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "s12m s12o", 85000, "total", 60,
     "Hands-on security training: finding weaknesses, defending networks and responding to incidents.",
     "Network security,Ethical hacking,Penetration testing,Digital forensics,Malware analysis,"
     "Kali Linux,SIEM tools,Incident response,Cyber law"),
    ("CSEH-ADV", "cseh-adv", "Cyber Security & Ethical Hacking (Advanced)", "Diploma",
     "School of Cyber Security", "1 year",
     "Graduation or diploma in computer science or IT, or equivalent knowledge.", 0,
     "Diploma,Bachelor's degree,Master's degree", "gcs", 95000, "total", 60,
     "Specialist training for people who already work with computers and want a security career.",
     "Red and blue teaming,Penetration testing,Cloud security,Threat intelligence,"
     "Security operations centre,Digital forensics,Vulnerability assessment"),
    ("APP", "app", "Advanced Python Programming", "Certificate",
     "School of Computing Sciences", "6 months",
     "Basic knowledge of programming or Python fundamentals.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "short", 35000, "total", 80,
     "A project-based certificate that takes you from solid Python basics to building and "
     "deploying real applications.",
     "Object-oriented programming,Automation,APIs,Django,Flask,Data analysis,Web scraping,"
     "Multithreading"),
    ("FSD", "fsd", "Full Stack Development", "Certificate",
     "School of Computing Sciences", "6 months",
     "Basic understanding of HTML, CSS and programming fundamentals.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "short", 45000, "total", 100,
     "Build complete web applications, from the interface to the database to deployment.",
     "HTML5 and CSS3,JavaScript,React,Node.js and Express,REST APIs,MongoDB,SQL databases,"
     "Git,Docker,Deployment"),
]

NOTICES = [
    ("Applications for the 2027\u201328 session are open", "Admissions",
     "Apply online until 30 April 2027. You get an application number immediately and can "
     "follow your progress with the tracker.", "2026-10-01"),
    ("Scholarship categories for 2027\u201328", "Scholarships",
     "Merit, sports, economically weaker section and girl-child scholarships are available. "
     "Amounts and eligibility are confirmed by the admissions office.", "2026-10-06"),
    ("Campus visits: book a slot", "Campus",
     "Prospective students and parents can visit the campus on weekdays. Contact the "
     "admissions office to reserve a time.", "2026-10-09"),
]

FACULTY = [
    ("Dr. Arindam Chaudhury", "Senior Professor and Dean", "School of Engineering & Applied Technology",
     "Distributed systems and neural networks"),
    ("Prof. Sarah Mathew", "Head of Department", "School of Management Studies",
     "Strategic marketing and corporate valuation"),
    ("Dr. Rajeev N. Verma", "Director of Research", "School of Computing Sciences",
     "Cryptographic protocols and blockchain architecture"),
    ("Dr. Elena Rostova", "Associate Professor", "School of Engineering & Applied Technology",
     "Optimisation and quantum physics models"),
]


FAQS = [
    ("Can I apply to more than one programme?",
     "Yes. Submit a separate application for each programme. You cannot have two open applications for "
     "the same programme with the same email.", 1),
    ("How will I know my application was received?",
     "You get an application number on screen as soon as you submit, and an email if the site has email "
     "switched on. Save the number. Create a student account to see all your applications in one place.", 2),
    ("How do I check my status?",
     "Log in to your student dashboard, or use the tracker with your application number and date of birth. "
     "Pending means received, Under Review means the office is checking your details, Approved means you "
     "can go to counselling, Waitlisted means you are in line for a seat, and Rejected means the "
     "application was not accepted.", 3),
    ("I made a mistake in my application. What now?",
     "While your status is Pending you can edit the application from your student dashboard. After that, "
     "contact the admissions office with your application number.", 4),
    ("Can I withdraw my application?",
     "Yes. Open the application in your student dashboard and choose Withdraw. The status changes to "
     "Cancelled and your seat is released.", 5),
    ("Is there an entrance test?",
     "Most programmes admit on merit. The MBA also needs a valid national entrance test score.", 6),
    ("How do I pay the fee?",
     "Fee payment instructions are given at counselling, after your application is approved. Do not pay "
     "anyone before that.", 7),
]

EVENTS = [
    ("Campus open day", "Meet faculty, see the labs and ask the admissions team your questions.",
     "MIUTM Campus, Ayodhya", "2026-11-07", None),
    ("Online admission help session", "A live walkthrough of the application form and eligibility rules.",
     "Online", "2027-01-16", None),
    ("Orientation week", "A week of introductions, lab tours and workshops for the new batch.",
     "MIUTM Campus, Ayodhya", "2027-08-02", "2027-08-06"),
]


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _random_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn, table, column, ddl):
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate(conn):
    """Bring a database created by an older version up to date. Safe to run every start."""
    _add_column(conn, "users", "full_name", "TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "users", "email", "TEXT")
    _add_column(conn, "users", "role", "TEXT NOT NULL DEFAULT 'admin'")
    _add_column(conn, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "users", "approved", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "courses", "is_published", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "faculty", "is_published", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "admissions", "student_id", "INTEGER")
    _add_column(conn, "contact_messages", "reply", "TEXT")
    _add_column(conn, "contact_messages", "replied_at", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admissions_student ON admissions(student_id)")


def init_db(app):
    """Create missing tables, seed empty ones and make sure an admin account exists."""
    path = app.config["DATABASE"]
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)

        # A write lock from here on: if two processes start together, the second waits and then
        # finds everything already created instead of creating it twice.
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
            conn.executemany(
                """INSERT INTO courses
                   (code, slug, name, level, school, duration, eligibility, min_percent, accepts,
                    audience, fee, fee_period, seats, summary, topics, sort_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [c + (i,) for i, c in enumerate(COURSES)],
            )
        if conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO notices (title, category, body, published_on) VALUES (?,?,?,?)", NOTICES
            )
        if conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] == 0:
            conn.executemany("INSERT INTO faqs (question, answer, sort_order) VALUES (?,?,?)", FAQS)
        if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO events (title, description, location, starts_on, ends_on) VALUES (?,?,?,?,?)",
                EVENTS)
        if conn.execute("SELECT COUNT(*) FROM faculty").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO faculty (name, designation, school, specialization) VALUES (?,?,?,?)",
                FACULTY,
            )

        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            username = (os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin").lower()
            password = os.environ.get("ADMIN_PASSWORD", "")
            generated = False
            if not password:
                password = _random_password()
                generated = True
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                (username, generate_password_hash(password), "Administrator"),
            )
            conn.commit()
            if generated:
                # Printed once. Only the hash is stored.
                print("=" * 64)
                print(" First run: administrator account created")
                print(f"   username: {username}")
                print(f"   password: {password}")
                print(" Save this now. It will not be shown again.")
                print(" Lost it? Run:  flask --app app create-admin " + username)
                print(" Tip: set ADMIN_USERNAME / ADMIN_PASSWORD env vars to choose your own.")
                print("=" * 64)
        conn.commit()
    finally:
        conn.close()
