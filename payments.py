"""
payments.py - fees and receipts.

Two fees: the application fee (paid to submit) and the admission fee (paid after selection). This version runs a
DEMONSTRATION gateway: no card or bank details are ever asked for or stored, and no money moves. The flow is the one a
real gateway needs (order, processing, success or failure, transaction record, receipt), so a real provider can
replace `run_demo` later without changing the rest.

Safety rules the code keeps:
 * one order per application and purpose, so retrying a failed payment never creates a second order;
 * state changes are compare-and-set (UPDATE ... WHERE status IN (...)), so a double click or two tabs cannot
   charge or confirm twice;
 * every state change is written to payment_events.
"""
import logging
import secrets
import string

from flask import request

import mailer
import notify
import site_data
import workflow
from audit import audit
from db import IntegrityError, get_db

log = logging.getLogger("miutm.payment")


def _order_id():
    return f"ORD-{site_data.today_ist().year}-{secrets.randbelow(90000000) + 10000000}"


def _txn_id():
    return "TXN" + "".join(secrets.choice(string.digits) for _ in range(12))


def _ref_id():
    return "PAY" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def event(conn, payment_id, status, note=None):
    conn.execute("INSERT INTO payment_events (payment_id, status, note) VALUES (?,?,?)", (payment_id, status, note))


def get_or_create(conn, admission, purpose, amount):
    """The one order for this application and purpose."""
    find = lambda: conn.execute("SELECT * FROM payments WHERE admission_id = ? AND purpose = ?",
                                (admission["id"], purpose)).fetchone()
    row = find()
    if row:
        return row
    for _ in range(8):
        try:
            cur = conn.execute("INSERT INTO payments (order_id, admission_id, student_id, purpose, amount) VALUES (?,?,?,?,?)",
                               (_order_id(), admission["id"], admission["student_id"], purpose, amount))
            event(conn, cur.lastrowid, "Pending", "Order created")
            conn.commit()
            return conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone()
        except IntegrityError:
            conn.rollback()
            row = find()
            if row:
                return row
    raise RuntimeError("could not create a payment order")


def start(conn, payment, method):
    """Pending, Failed or Cancelled -> Processing. False if it is already processing or paid."""
    cur = conn.execute("UPDATE payments SET status = 'Processing', method = ?, attempts = attempts + 1, failure_reason = NULL, "
                       "updated_at = datetime('now') WHERE id = ? AND status IN ('Pending', 'Failed', 'Cancelled')",
                       (method, payment["id"]))
    if cur.rowcount != 1:
        conn.rollback()
        return False
    event(conn, payment["id"], "Processing", f"Attempt {payment['attempts'] + 1} by {method}")
    conn.commit()
    return True


def succeed(conn, payment_id):
    """Processing -> Successful, then do what the payment was for. Returns True if this call completed it."""
    for _ in range(3):
        try:
            cur = conn.execute(
                "UPDATE payments SET status = 'Successful', transaction_id = ?, payment_ref = ?, paid_at = datetime('now'), "
                "updated_at = datetime('now'), failure_reason = NULL WHERE id = ? AND status = 'Processing'",
                (_txn_id(), _ref_id(), payment_id))
            break
        except IntegrityError:  # an id collision: pick new ones
            conn.rollback()
    if cur.rowcount != 1:
        conn.rollback()
        return False
    event(conn, payment_id, "Successful", "Payment received")
    p = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    a = conn.execute("SELECT * FROM admissions WHERE id = ?", (p["admission_id"],)).fetchone()
    link = f"/student/applications/{a['application_no']}"
    notify.notify(p["student_id"], "Payment successful", f"{p['purpose']}: Rs. {p['amount']}. Transaction {p['transaction_id']}.",
                  f"/student/payments/{p['order_id']}", "payment")
    if p["purpose"] == "Application Fee":
        conn.execute("UPDATE admissions SET payment_status = 'Paid' WHERE id = ?", (a["id"],))
        if a["status"] == "Payment Pending":
            workflow.set_status(a, "Submitted", note="Application fee paid. Your application is submitted.", quiet=True)
    elif a["status"] in ("Selected", "Admission Fee Pending"):
        workflow.set_status(a, "Approved", note="Admission fee paid. Your admission is approved.", quiet=True)
    audit("payment", p["order_id"], f"{p['purpose']} Rs. {p['amount']} successful", commit=False)
    conn.commit()
    log.info("payment successful", extra={"event": "payment_success", "payment_id": p["id"], "amount": p["amount"], "purpose": p["purpose"]})
    a = conn.execute("SELECT * FROM admissions WHERE id = ?", (a["id"],)).fetchone()
    mailer.payment_confirmation(a, p, request.url_root)
    if p["purpose"] == "Application Fee":
        mailer.application_received(a, request.url_root)
    return True


def fail(conn, payment_id, reason):
    cur = conn.execute("UPDATE payments SET status = 'Failed', failure_reason = ?, updated_at = datetime('now') "
                       "WHERE id = ? AND status = 'Processing'", (reason[:200], payment_id))
    if cur.rowcount != 1:
        conn.rollback()
        return False
    event(conn, payment_id, "Failed", reason[:200])
    p = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    notify.notify(p["student_id"], "Payment failed", "Your payment did not go through. You can try again.",
                  f"/student/payments/{p['order_id']}", "payment")
    conn.commit()
    log.warning("payment failed", extra={"event": "payment_failed", "payment_id": payment_id})
    return True


def cancel(conn, payment):
    cur = conn.execute("UPDATE payments SET status = 'Cancelled', updated_at = datetime('now') "
                       "WHERE id = ? AND status IN ('Pending', 'Failed')", (payment["id"],))
    if cur.rowcount == 1:
        event(conn, payment["id"], "Cancelled", "Cancelled by the student")
    conn.commit()
    return cur.rowcount == 1


def run_demo(conn, payment, method, simulate_failure=False):
    """The demonstration gateway. Returns 'success', 'failed', 'busy' (already processing) or 'paid'."""
    if payment["status"] == "Successful":
        return "paid"
    if not start(conn, payment, method):
        row = conn.execute("SELECT status FROM payments WHERE id = ?", (payment["id"],)).fetchone()
        return "paid" if row and row["status"] == "Successful" else "busy"
    if simulate_failure:
        fail(conn, payment["id"], "The payment was declined (simulated for the demonstration).")
        return "failed"
    succeed(conn, payment["id"])
    return "success"


def refund(conn, payment, reason):
    """Successful -> Refunded. Staff only."""
    cur = conn.execute("UPDATE payments SET status = 'Refunded', refund_reason = ?, refunded_at = datetime('now'), "
                       "updated_at = datetime('now') WHERE id = ? AND status = 'Successful'", (reason[:300], payment["id"]))
    if cur.rowcount != 1:
        conn.rollback()
        return False
    event(conn, payment["id"], "Refunded", reason[:300])
    if payment["purpose"] == "Application Fee":
        conn.execute("UPDATE admissions SET payment_status = 'Refunded' WHERE id = ?", (payment["admission_id"],))
    notify.notify(payment["student_id"], "Payment refunded", f"{payment['purpose']}: Rs. {payment['amount']}. {reason}"[:600],
                  f"/student/payments/{payment['order_id']}", "payment")
    audit("refund", payment["order_id"], f"Rs. {payment['amount']}", commit=False)
    conn.commit()
    return True
