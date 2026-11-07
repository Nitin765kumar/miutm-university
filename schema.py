"""
schema.py - the database layout, written once and used for both SQLite (local, tests) and PostgreSQL (production).

Tokens like {PK} are replaced per engine. Tables are created if missing; MIGRATIONS (in db.py) bring an older
database up to date. Nothing here ever deletes data.
"""

TABLES = [
"""CREATE TABLE IF NOT EXISTS users (
    id {PK}, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '', email TEXT, role TEXT NOT NULL DEFAULT 'admin',
    is_active INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 1,
    created_at {TS} NOT NULL DEFAULT {NOW}, last_login {TS})""",
"""CREATE TABLE IF NOT EXISTS students (
    id {PK}, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, full_name TEXT NOT NULL, phone TEXT,
    is_active INTEGER NOT NULL DEFAULT 1, email_verified INTEGER NOT NULL DEFAULT 0,
    created_at {TS} NOT NULL DEFAULT {NOW}, last_login {TS})""",
"""CREATE TABLE IF NOT EXISTS courses (
    id {PK}, code TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL UNIQUE,
    level TEXT NOT NULL, school TEXT NOT NULL, duration TEXT NOT NULL, eligibility TEXT NOT NULL,
    min_percent INTEGER NOT NULL DEFAULT 0, accepts TEXT NOT NULL, audience TEXT NOT NULL,
    fee INTEGER NOT NULL CHECK (fee >= 0), fee_period TEXT NOT NULL, seats INTEGER NOT NULL CHECK (seats >= 0),
    summary TEXT NOT NULL, topics TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
    is_published INTEGER NOT NULL DEFAULT 1, admission_fee INTEGER NOT NULL DEFAULT 0,
    overview TEXT NOT NULL DEFAULT '', careers TEXT NOT NULL DEFAULT '', outcomes TEXT NOT NULL DEFAULT '')""",
"""CREATE TABLE IF NOT EXISTS subjects (
    id {PK}, course_code TEXT NOT NULL REFERENCES courses(code) ON DELETE CASCADE, semester INTEGER NOT NULL,
    code TEXT NOT NULL, name TEXT NOT NULL, credits INTEGER NOT NULL CHECK (credits >= 0), kind TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0, UNIQUE (course_code, code))""",
"""CREATE TABLE IF NOT EXISTS subject_units (
    id {PK}, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    unit_no INTEGER NOT NULL, title TEXT NOT NULL, UNIQUE (subject_id, unit_no))""",
"""CREATE TABLE IF NOT EXISTS admissions (
    id {PK}, application_no TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, father_name TEXT NOT NULL,
    mother_name TEXT NOT NULL, gender TEXT NOT NULL, dob {DATE} NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
    category TEXT, nationality TEXT NOT NULL DEFAULT 'Indian', qualification TEXT NOT NULL,
    percentage {NUM} NOT NULL, course_code TEXT NOT NULL, course_name TEXT NOT NULL, address TEXT NOT NULL,
    city TEXT NOT NULL, state TEXT NOT NULL, pincode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Submitted',
    remarks TEXT, student_id INTEGER REFERENCES students(id) ON DELETE SET NULL, session TEXT,
    payment_status TEXT NOT NULL DEFAULT 'Unpaid', merit_score {NUM}, merit_rank INTEGER, rejection_reason TEXT,
    submitted_at {TS}, created_at {TS} NOT NULL DEFAULT {NOW}, updated_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS admission_events (
    id {PK}, admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE, status TEXT NOT NULL,
    previous_status TEXT, changed_by TEXT, note TEXT, created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS documents (
    id {PK}, admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE, doc_type TEXT NOT NULL,
    filename TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, data {BLOB} NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending', note TEXT, reviewed_by TEXT, reviewed_at {TS},
    uploaded_at {TS} NOT NULL DEFAULT {NOW}, UNIQUE (admission_id, doc_type))""",
"""CREATE TABLE IF NOT EXISTS document_events (
    id {PK}, admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE, doc_type TEXT NOT NULL,
    action TEXT NOT NULL, note TEXT, actor TEXT, created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS drafts (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE, data TEXT NOT NULL,
    updated_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS draft_documents (
    id {PK}, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE, doc_type TEXT NOT NULL,
    filename TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, data {BLOB} NOT NULL,
    uploaded_at {TS} NOT NULL DEFAULT {NOW}, UNIQUE (student_id, doc_type))""",
"""CREATE TABLE IF NOT EXISTS merit_publications (
    id {PK}, course_code TEXT NOT NULL REFERENCES courses(code) ON DELETE CASCADE, session TEXT NOT NULL,
    published_at {TS} NOT NULL DEFAULT {NOW}, published_by TEXT, UNIQUE (course_code, session))""",
"""CREATE TABLE IF NOT EXISTS payments (
    id {PK}, order_id TEXT NOT NULL UNIQUE, admission_id INTEGER NOT NULL REFERENCES admissions(id),
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL, purpose TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount >= 0), currency TEXT NOT NULL DEFAULT 'INR', method TEXT,
    status TEXT NOT NULL DEFAULT 'Pending', transaction_id TEXT UNIQUE, payment_ref TEXT UNIQUE,
    failure_reason TEXT, refund_reason TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    created_at {TS} NOT NULL DEFAULT {NOW}, updated_at {TS} NOT NULL DEFAULT {NOW}, paid_at {TS}, refunded_at {TS},
    UNIQUE (admission_id, purpose))""",
"""CREATE TABLE IF NOT EXISTS payment_events (
    id {PK}, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE, status TEXT NOT NULL,
    note TEXT, created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS notifications (
    id {PK}, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE, title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '', link TEXT, kind TEXT NOT NULL DEFAULT 'info', is_read INTEGER NOT NULL DEFAULT 0,
    created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS email_log (
    id {PK}, to_email TEXT NOT NULL, subject TEXT NOT NULL, body TEXT, status TEXT NOT NULL DEFAULT 'Pending',
    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at {TS} NOT NULL DEFAULT {NOW}, sent_at {TS})""",
"""CREATE TABLE IF NOT EXISTS contact_messages (
    id {PK}, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT, department TEXT NOT NULL, subject TEXT NOT NULL,
    message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, reply TEXT, replied_at {TS},
    created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS tickets (
    id {PK}, ticket_no TEXT NOT NULL UNIQUE, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT,
    category TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
    response TEXT, created_at {TS} NOT NULL DEFAULT {NOW}, updated_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS notices (
    id {PK}, title TEXT NOT NULL, category TEXT NOT NULL, body TEXT NOT NULL, published_on {DATE} NOT NULL,
    is_published INTEGER NOT NULL DEFAULT 1)""",
"""CREATE TABLE IF NOT EXISTS events (
    id {PK}, title TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL DEFAULT '',
    starts_on {DATE} NOT NULL, ends_on {DATE}, is_published INTEGER NOT NULL DEFAULT 1)""",
"""CREATE TABLE IF NOT EXISTS faqs (
    id {PK}, question TEXT NOT NULL, answer TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
    is_published INTEGER NOT NULL DEFAULT 1)""",
"""CREATE TABLE IF NOT EXISTS faculty (
    id {PK}, name TEXT NOT NULL, designation TEXT NOT NULL, school TEXT NOT NULL, specialization TEXT NOT NULL,
    is_published INTEGER NOT NULL DEFAULT 1)""",
"""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS audit_log (
    id {PK}, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '', created_at {TS} NOT NULL DEFAULT {NOW})""",
"""CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at {TS} NOT NULL DEFAULT {NOW})""",
]

# Created after the migrations, because they may refer to columns the migrations add.
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_admissions_status ON admissions(status)",
    "CREATE INDEX IF NOT EXISTS idx_admissions_email ON admissions(email)",
    "CREATE INDEX IF NOT EXISTS idx_admissions_created ON admissions(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_admissions_student ON admissions(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_admissions_course ON admissions(course_code)",
    "CREATE INDEX IF NOT EXISTS idx_admissions_session ON admissions(session)",
    # Server-side duplicate rule: one live application per student, programme and session.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_live_application ON admissions(student_id, course_code, session) "
    "WHERE status NOT IN ('Cancelled', 'Rejected')",
    "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)",
    "CREATE INDEX IF NOT EXISTS idx_events_admission ON admission_events(admission_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
    "CREATE INDEX IF NOT EXISTS idx_payments_student ON payments(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_student ON notifications(student_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_subjects_course ON subjects(course_code, semester)",
    "CREATE INDEX IF NOT EXISTS idx_email_status ON email_log(status)",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)",
]

# Parents before children: the order used to restore a backup.
RESTORE_ORDER = ["courses", "students", "users", "settings", "notices", "events", "faqs", "faculty", "contact_messages",
                 "tickets", "subjects", "subject_units", "admissions", "admission_events", "documents", "document_events",
                 "drafts", "draft_documents", "merit_publications", "payments", "payment_events", "notifications",
                 "email_log", "audit_log", "schema_migrations"]

TABLES_WITHOUT_ID = {"settings", "drafts"}  # primary key is not a serial 'id'


def render(sql, postgres):
    """Fill in the engine-specific words."""
    pg = {"{PK}": "SERIAL PRIMARY KEY", "{TS}": "TIMESTAMP", "{DATE}": "DATE", "{BLOB}": "BYTEA",
          "{NUM}": "NUMERIC(5,1)", "{NOW}": "(now() AT TIME ZONE 'utc')"}
    lite = {"{PK}": "INTEGER PRIMARY KEY AUTOINCREMENT", "{TS}": "TEXT", "{DATE}": "TEXT", "{BLOB}": "BLOB",
            "{NUM}": "REAL", "{NOW}": "(datetime('now'))"}
    for token, value in (pg if postgres else lite).items():
        sql = sql.replace(token, value)
    return sql
