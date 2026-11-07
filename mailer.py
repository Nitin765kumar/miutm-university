"""
mailer.py - optional email, with a delivery record.

Email is off until SMTP_HOST is set. Every message that is sent is recorded in `email_log` with a state:
Pending, Sent, Failed or Retrying. A failure is recorded and never stops the action that caused it (the
application, the payment). Failed messages can be retried from the staff area or with `flask retry-emails`.
Only the state and a short error name are logged, never the message text, the address or any password.
"""
import logging
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

import db as dbm
import site_data

log = logging.getLogger("miutm.mail")


def email_enabled():
    return bool(current_app.config.get("MAIL_BACKEND") or current_app.config.get("SMTP_HOST"))


def _clean(text):
    return " ".join(str(text).split())


def _own(app):
    return dbm.connect_standalone(app)  # a separate connection, so the record survives whatever the request does


def _record(app, to, subject, body):
    conn = _own(app)
    try:
        cur = conn.execute("INSERT INTO email_log (to_email, subject, body) VALUES (?,?,?)", (to, subject, body))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _finish(app, log_id, ok, error=None):
    conn = _own(app)
    try:
        if ok:
            conn.execute("UPDATE email_log SET status = 'Sent', sent_at = datetime('now'), attempts = attempts + 1, "
                         "last_error = NULL, body = NULL WHERE id = ?", (log_id,))
        else:
            conn.execute("UPDATE email_log SET status = 'Failed', attempts = attempts + 1, last_error = ? WHERE id = ?",
                         (error, log_id))
        conn.commit()
    finally:
        conn.close()


def _deliver(app, to, subject, body):
    """Returns None on success, or a short error text."""
    backend = app.config.get("MAIL_BACKEND")  # used by the tests
    try:
        if backend:
            backend(to, subject, body)
            return None
        cfg = app.config
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg["SMTP_FROM"], to, subject
        msg.set_content(body)
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as smtp:
            if cfg["SMTP_TLS"]:
                smtp.starttls()
            if cfg["SMTP_USER"]:
                smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)
        return None
    except Exception as exc:  # never raise into the request
        return f"{type(exc).__name__}: {str(exc)[:160]}"


def send_mail(to, subject, body):
    """Hand a message to the mail system. Returns True if it was accepted for sending."""
    if not to or not email_enabled():
        return False
    app = current_app._get_current_object()
    subject = _clean(subject)
    try:
        log_id = _record(app, to, subject, body)
    except Exception:
        log.exception("could not record an email", extra={"event": "email_record_failed"})
        log_id = None

    def work():
        error = _deliver(app, to, subject, body)
        if error:
            log.error("email failed", extra={"event": "email_failed", "email_id": log_id, "error": error.split(":")[0]})
        if log_id:
            try:
                _finish(app, log_id, error is None, error)
            except Exception:
                log.exception("could not update an email record", extra={"event": "email_record_failed"})

    if app.config.get("MAIL_BACKEND"):
        work()  # tests run it inline
    else:
        threading.Thread(target=work, daemon=True).start()
    return True


def retry_failed(app, limit=25):
    """Try the Failed messages again (up to 5 attempts each). Returns (sent, failed)."""
    conn = _own(app)
    try:
        rows = conn.execute("SELECT id, to_email, subject, body FROM email_log WHERE status IN ('Failed', 'Retrying') "
                            "AND attempts < 5 AND body IS NOT NULL ORDER BY id LIMIT ?", (limit,)).fetchall()
        for r in rows:
            conn.execute("UPDATE email_log SET status = 'Retrying' WHERE id = ?", (r["id"],))
        conn.commit()
    finally:
        conn.close()
    sent = failed = 0
    for r in rows:
        error = _deliver(app, r["to_email"], r["subject"], r["body"])
        _finish(app, r["id"], error is None, error)
        sent, failed = (sent + 1, failed) if error is None else (sent, failed + 1)
    return sent, failed


# ---------------------------------------------------------------------------
# The messages
# ---------------------------------------------------------------------------
def _sign(extra=""):
    s = site_data.current_site()
    return f"\n\n{extra}{s['name']}\n{', '.join(s['address'])}\n{s['phone']}"


def application_received(a, base_url):
    send_mail(a["email"], f"Application received: {a['application_no']}",
              f"Dear {a['full_name']},\n\nWe have received your application for {a['course_name']}.\n\n"
              f"Application number: {a['application_no']}\n\nSign in to your dashboard to follow it, upload documents and "
              f"download your receipt: {base_url}student/dashboard" + _sign())


def payment_confirmation(a, payment, base_url):
    send_mail(a["email"], f"Payment successful: {payment['order_id']}",
              f"Dear {a['full_name']},\n\nYour payment was successful.\n\nPurpose: {payment['purpose']}\n"
              f"Amount: Rs. {payment['amount']}\nTransaction ID: {payment['transaction_id']}\nApplication: {a['application_no']}\n\n"
              f"Download your receipt from your dashboard: {base_url}student/dashboard" + _sign())


def status_changed(a, status, note, base_url):
    lines = [f"Dear {a['full_name']},", "",
             f"The status of your application {a['application_no']} ({a['course_name']}) is now: {status}.",
             site_data.STATUS_HELP.get(status, "")]
    if note:
        lines += ["", f"Message from the admissions office: {note}"]
    lines += ["", f"Details: {base_url}student/dashboard"]
    send_mail(a["email"], f"Application {a['application_no']}: {status}", "\n".join(lines) + _sign())


def ticket_received(t):
    send_mail(t["email"], f"Ticket {t['ticket_no']} received",
              f"Dear {t['name']},\n\nWe have received your message: \"{t['subject']}\".\n"
              f"Your ticket number is {t['ticket_no']}. Keep it to check the answer on the support page." + _sign())


def ticket_updated(t):
    send_mail(t["email"], f"Ticket {t['ticket_no']}: {t['status']}",
              f"Dear {t['name']},\n\nYour ticket {t['ticket_no']} (\"{t['subject']}\") is now {t['status']}.\n\n"
              f"{t['response'] or ''}" + _sign())


def message_reply(m, text):
    return send_mail(m["email"], f"Re: {m['subject']}", f"Dear {m['name']},\n\n{text}" + _sign())


def password_reset(person, url):
    return send_mail(person["email"], "Reset your MIUTM password",
                     f"Dear {person['full_name']},\n\nUse this link to choose a new password. It works once and "
                     f"expires in one hour:\n\n{url}\n\nIf you did not ask for this, ignore this email." + _sign())


def email_verification(student, url):
    return send_mail(student["email"], "Confirm your email address",
                     f"Dear {student['full_name']},\n\nPlease confirm your email address to finish setting up your "
                     f"MIUTM account. The link works for 3 days:\n\n{url}\n\nIf you did not create an account, "
                     f"ignore this email." + _sign())
