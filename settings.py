"""
settings.py - values that administrators edit in the browser (Staff area > Settings).

They are stored in the `settings` table and override the defaults in site_data.py.
`apply()` runs at the start of every request, so a change shows up on every page immediately,
on every server process.
"""
from datetime import date

from flask import g

import site_data
import validators

DATE_KEYS = [("opens", "Applications open"), ("closes", "Applications close"), ("merit", "Merit list published"),
             ("counselling", "Counselling and seat confirmation"), ("classes", "Classes begin")]


def load(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def apply(conn):
    over = load(conn)
    g.settings = over
    g.site = site_data.build_site(over)
    g.cycle = site_data.build_cycle(over)
    g.force_open = over.get("force_open") == "1"


def current_values():
    """What the settings form should show: the effective values."""
    site, cycle = site_data.current_site(), site_data.current_cycle()
    values = {"session": cycle["session"], "phone": site["phone"], "phone_alt": site["phone_alt"],
              "hours": site["hours"], "general_email": site["general_email"],
              "force_open": "1" if g.get("force_open") else ""}
    for i in range(3):
        values[f"address{i + 1}"] = site["address"][i] if i < len(site["address"]) else ""
    for m in cycle["milestones"]:
        values[m["key"]] = m["date"].isoformat()
    return values


def parse(form):
    errors, v = {}, {}
    clean = lambda k, n: " ".join((form.get(k) or "").split())[:n]

    v["session"] = clean("session", 12)
    if not v["session"]:
        errors["session"] = "Enter the session, like 2027-28."

    parsed = {}
    for key, label in DATE_KEYS:
        raw = clean(key, 10)
        v[key] = raw
        try:
            parsed[key] = date.fromisoformat(raw)
        except ValueError:
            errors[key] = f"Enter a valid date for: {label.lower()}."
    if not errors:
        order = [k for k, _ in DATE_KEYS]
        for earlier, later in zip(order, order[1:]):
            if parsed[later] < parsed[earlier]:
                errors[later] = "This date cannot be before the previous step."
                break
        if parsed["closes"] <= parsed["opens"]:
            errors["closes"] = "Applications must close after they open."

    v["phone"] = clean("phone", 25)
    if len(v["phone"]) < 6:
        errors["phone"] = "Enter the main phone number."
    v["phone_alt"] = clean("phone_alt", 25)
    v["hours"] = clean("hours", 80)
    if not v["hours"]:
        errors["hours"] = "Enter the office hours."
    v["general_email"] = clean("general_email", 120).lower()
    if not validators.EMAIL_RE.match(v["general_email"]):
        errors["general_email"] = "Enter a valid email address."
    for i in (1, 2, 3):
        v[f"address{i}"] = clean(f"address{i}", 80)
    if not v["address1"]:
        errors["address1"] = "Enter at least the first address line."
    v["force_open"] = "1" if form.get("force_open") == "1" else "0"
    return v, errors


def save(conn, values):
    for key, value in values.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))
    conn.commit()
