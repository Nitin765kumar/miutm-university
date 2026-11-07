"""
dbtools.py - backup, restore, import from the old SQLite file, and the database self-check.

A backup is one gzip-compressed JSON file that holds every table (applications, documents, payments, accounts,
notifications, messages, audit log, settings). It is the same format on SQLite and PostgreSQL, so a backup from
one can be restored into the other.
"""
import base64
import gzip
import json
import sqlite3
from datetime import datetime, timezone

import db as dbm
import schema

FORMAT = "miutm-backup"
VERSION = 5


def _jsonable(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _restore_value(value):
    if isinstance(value, dict) and "__b64__" in value:
        return base64.b64decode(value["__b64__"])
    return value


def _columns_of(cur):
    return list(cur.columns) if hasattr(cur, "columns") else [d[0] for d in cur.description]


def dump(conn):
    """Everything in the database as plain data."""
    tables = {}
    for name in schema.RESTORE_ORDER:
        cur = conn.execute(f"SELECT * FROM {name}")
        cols = _columns_of(cur)
        rows = [[_jsonable(v) for v in row] for row in cur.fetchall()]
        tables[name] = {"columns": cols, "rows": rows}
    return {"format": FORMAT, "version": VERSION, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tables": tables}


def to_bytes(conn):
    return gzip.compress(json.dumps(dump(conn)).encode("utf-8"))


def read_backup(raw):
    data = json.loads(gzip.decompress(raw).decode("utf-8")) if raw[:2] == b"\x1f\x8b" else json.loads(raw.decode("utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("This file is not a MIUTM backup.")
    return data


def _fix_sequences(conn, postgres):
    if not postgres:
        return
    for name in schema.RESTORE_ORDER:
        if name in schema.TABLES_WITHOUT_ID or name == "schema_migrations":
            continue
        conn.execute(
            f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), COALESCE((SELECT MAX(id) FROM {name}), 1), "
            f"(SELECT MAX(id) FROM {name}) IS NOT NULL)")


def restore(conn, data, postgres):
    """Replace the contents of every table with the backup. Runs as one transaction: all or nothing."""
    tables = data["tables"]
    try:
        for name in reversed(schema.RESTORE_ORDER):  # children first
            conn.execute(f"DELETE FROM {name}")
        for name in schema.RESTORE_ORDER:
            t = tables.get(name)
            if not t or not t["rows"]:
                continue
            cols = t["columns"]
            sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            conn.executemany(sql, [[_restore_value(v) for v in row] for row in t["rows"]])
        _fix_sequences(conn, postgres)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {name: len(tables.get(name, {}).get("rows", [])) for name in schema.RESTORE_ORDER}


def import_sqlite(conn, path, postgres):
    """Copy a version 4 SQLite file into the current database, then bring its rows up to date."""
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    tables = {}
    for name in schema.RESTORE_ORDER:
        if name not in have or name == "schema_migrations":
            continue
        cur = src.execute(f"SELECT * FROM {name}")
        cols = [d[0] for d in cur.description]
        tables[name] = {"columns": cols, "rows": [[_jsonable(v) for v in row] for row in cur.fetchall()]}
    src.close()
    legacy = "admissions" in tables and "payment_status" not in tables["admissions"]["columns"]
    counts = restore(conn, {"tables": tables}, postgres)
    for mid, name, _ in dbm.MIGRATIONS:  # the restore emptied the record of applied migrations
        conn.execute("INSERT INTO schema_migrations (id, name) VALUES (?, ?)", (mid, name))
    if legacy:
        dbm.legacy_fixups(conn)
    conn.commit()
    return counts


def check(conn, postgres):
    """A self-test for the database. Returns a list of (name, passed, detail)."""
    results = []

    def step(name, fn):
        try:
            results.append((name, True, fn() or ""))
        except Exception as exc:
            conn.rollback()
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    def version():
        row = conn.execute("SELECT version()" if postgres else "SELECT sqlite_version()").fetchone()
        return str(row[0])[:70]

    def tables():
        for name in schema.RESTORE_ORDER:
            conn.execute(f"SELECT 1 FROM {name} LIMIT 1").fetchall()
        return f"{len(schema.RESTORE_ORDER)} tables readable"

    def migrations():
        n = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert n >= len(dbm.MIGRATIONS), f"{n} of {len(dbm.MIGRATIONS)} migrations applied"
        return f"{n} migrations applied"

    def roundtrip():
        conn.execute(schema.render("CREATE TEMP TABLE _chk (id {PK}, b {BLOB}, n {NUM}, d {DATE}, t {TS}, s TEXT)", postgres))
        conn.execute("INSERT INTO _chk (b, n, d, t, s) VALUES (?, ?, ?, ?, ?)",
                     (b"\x00\xffbinary", 72.5, "2026-10-17", "2026-10-17 11:02:12", "text"))
        row = conn.execute("SELECT b, n, d, t, s FROM _chk").fetchone()
        assert bytes(row["b"]) == b"\x00\xffbinary", "binary data changed"
        assert float(row["n"]) == 72.5, "number changed"
        assert str(row["d"])[:10] == "2026-10-17", f"date came back as {row['d']!r}"
        assert str(row["t"])[:19] == "2026-10-17 11:02:12", f"timestamp came back as {row['t']!r}"
        conn.execute("DROP TABLE _chk")
        conn.commit()
        return "binary, number, date and timestamp round-trip"

    def lastid():
        cur = conn.execute("INSERT INTO audit_log (actor, role, action) VALUES ('db-check', 'system', 'check')")
        assert cur.lastrowid, "no id returned from INSERT"
        found = conn.execute("SELECT COUNT(*) FROM audit_log WHERE id = ?", (cur.lastrowid,)).fetchone()[0]
        conn.rollback()
        gone = conn.execute("SELECT COUNT(*) FROM audit_log WHERE actor = 'db-check'").fetchone()[0]
        assert found == 1 and gone == 0, "transaction rollback did not work"
        return "inserts return an id; rollback undoes them"

    def unique():
        conn.execute("INSERT INTO settings (key, value) VALUES ('_chk', '1')")
        try:
            conn.execute("INSERT INTO settings (key, value) VALUES ('_chk', '2')")
            raise AssertionError("duplicate key was accepted")
        except dbm.IntegrityError:
            conn.rollback()
        conn.execute("SELECT 1").fetchone()  # the connection must still work after the error
        return "duplicates are refused and the connection recovers"

    def duplicate_rule():
        row = conn.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'uq_live_application'" if postgres else
                           "SELECT COUNT(*) FROM sqlite_master WHERE name = 'uq_live_application'").fetchone()
        assert row[0] == 1, "the one-live-application-per-programme rule is missing"
        return "duplicate-application rule is in the database"

    def like():
        conn.execute("INSERT INTO settings (key, value) VALUES ('_chk', 'Python')")
        n = conn.execute("SELECT COUNT(*) FROM settings WHERE LOWER(value) LIKE ? ESCAPE '\\'", ("%pyth%",)).fetchone()[0]
        conn.rollback()
        assert n == 1, "case-insensitive search does not work"
        return "case-insensitive search works"

    for name, fn in (("Server", version), ("Tables", tables), ("Migrations", migrations), ("Data types", roundtrip),
                     ("Row ids and rollback", lastid), ("Unique constraints", unique),
                     ("Duplicate-application rule", duplicate_rule), ("Search", like)):
        step(name, fn)
    return results
