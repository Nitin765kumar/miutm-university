"""
mailer.py - optional email.

Email is OFF until you set SMTP_HOST (see README). When it is off, every function here simply
returns False and the site keeps working; the pages tell people not to expect an email.
Sending happens in a background thread so a slow mail server never slows a page down.
"""
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

import site_data


def email_enabled():
    return bool(current_app.config.get("MAIL_BACKEND") or current_app.config.get("SMTP_HOST"))


def _clean(text):
    return " ".join(str(text).split())


def send_mail(to, subject, body):
    """Returns True if the message was handed to the mail system."""
    if not to or not email_enabled():
        return False
    backend = current_app.config.get("MAIL_BACKEND")  # used by the tests
    if backend:
        backend(to, _clean(subject), body)
        return True

    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to
    msg["Subject"] = _clean(subject)
    msg.set_content(body)
    app = current_app._get_current_object()

    def worker():
        try:
            with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as smtp:
                if cfg["SMTP_TLS"]:
                    smtp.starttls()
                if cfg["SMTP_USER"]:
                    smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                smtp.send_message(msg)
        except Exception:  # never let a mail problem break a request
            app.logger.exception("Could not send email to %s", to)

    threading.Thread(target=worker, daemon=True).start()
    return True


def _sign(extra=""):
    s = site_data.current_site()
    return f"\n\n{extra}{s['name']}\n{', '.join(s['address'])}\n{s['phone']}"


def application_received(a, base_url):
    send_mail(a["email"], f"Application received: {a['application_no']}",
              f"Dear {a['full_name']},\n\nWe have received your application for {a['course_name']}.\n\n"
              f"Application number: {a['application_no']}\n\n"
              f"Track it any time at {base_url}track with your application number and date of birth, "
              f"or create a student account at {base_url}student/register to manage it and upload documents."
              + _sign())


def status_changed(a, status, note, base_url):
    lines = [f"Dear {a['full_name']},", "",
             f"The status of your application {a['application_no']} ({a['course_name']}) is now: {status}.",
             site_data.STATUS_HELP.get(status, "")]
    if note:
        lines += ["", f"Message from the admissions office: {note}"]
    lines += ["", f"Details: {base_url}track"]
    send_mail(a["email"], f"Application {a['application_no']}: {status}", "\n".join(lines) + _sign())


def ticket_received(t):
    send_mail(t["email"], f"Ticket {t['ticket_no']} received",
              f"Dear {t['name']},\n\nWe have received your message: \"{t['subject']}\".\n"
              f"Your ticket number is {t['ticket_no']}. Keep it to check the answer on the support page."
              + _sign())


def ticket_updated(t):
    send_mail(t["email"], f"Ticket {t['ticket_no']}: {t['status']}",
              f"Dear {t['name']},\n\nYour ticket {t['ticket_no']} (\"{t['subject']}\") is now {t['status']}.\n\n"
              f"{t['response'] or ''}" + _sign())


def message_reply(m, text):
    return send_mail(m["email"], f"Re: {m['subject']}", f"Dear {m['name']},\n\n{text}" + _sign())


def password_reset(student, url):
    return send_mail(student["email"], "Reset your MIUTM password",
                     f"Dear {student['full_name']},\n\nUse this link to choose a new password. It works once "
                     f"and expires in one hour:\n\n{url}\n\nIf you did not ask for this, ignore this email."
                     + _sign())
