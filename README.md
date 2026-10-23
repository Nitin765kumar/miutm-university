# MIUTM Portal, version 4

Maurya International University of Technology & Management: a Flask website with public pages,
online admission, **student accounts and dashboard**, a **staff area with roles**, document
verification, merit lists, offer letters, news and events, help tickets, reports and backups.

> **Demonstration project.** The institution, its figures and contact details are sample data. A
> ribbon on every page says so. Set `DEMO_MODE=0` only for a real, recognised institution.

## What is in it

**Visitors**
- Home with a programme finder; About; Programmes (search, filters, detail pages)
- Admissions guide, scholarships, news and events, FAQ (from the database), site search
- Online application (4 steps), tracker (application number + date of birth)
- Contact form and a help / grievance form with ticket numbers and a status page

**Students** (Sign up / Log in buttons in the header; a student account is needed to apply)
- Account with email and password; reset by email when email is set up
- **Five-step application** that saves a draft at every step: personal details, contact, education and
  programme, **documents**, then a **review** that looks exactly like the printed form. Every step has
  Back, Save and Cancel; progress can be finished later from the dashboard
- Stay signed in: "Keep me signed in" (on by default) keeps you logged in for 90 days since your last
  visit, until you log out. Staff and student sign-ins do not affect each other
- Dashboard: every application, status timeline, next step, document progress
- Upload documents (PDF, JPG, PNG up to 2 MB); the office verifies each one
- Edit while *Pending*, withdraw (becomes *Cancelled*), print the application form
- Offer letter once *Approved* or *Enrolled*
- Applications made without an account can be added with application number + date of birth

**Staff** (**Admin Login / Register** buttons in the bar above the menu, or `/admin`)
- **Admin register** creates a *Reviewer* account that stays switched off until an administrator approves
  it (Staff accounts > Waiting for approval). Set `STAFF_SIGNUP_CODE` to also require a code
- **Site settings**: admission session, all five key dates, phone, email, address and office hours,
  editable in the browser; changes go live on every page immediately
- Dashboard "Needs your attention" panel and quick actions
- Roles: **Administrator** (everything) and **Reviewer** (review applications and documents, answer
  messages and tickets, see reports; cannot delete, run merit lists, change content or manage staff)
- Applications: search, filter, export CSV, edit, print, change status (Pending, Under Review,
  Approved, Waitlisted, Enrolled, Rejected, Cancelled) with a note the applicant sees
- Merit lists per programme with seat counts; one click approves the top applicants and
  waitlists the rest
- Document verification queue; messages with email replies; tickets; student accounts
- Website content manager: programmes, notices, events, faculty and FAQs (add, edit, hide, delete)
- Reports with charts, activity log (who did what), staff accounts, full database backup

## Run it on your computer

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000. On the **first start** the terminal prints the first administrator's
username and a generated password. Copy it; only a hash is stored. To choose your own, set
`ADMIN_USERNAME` and `ADMIN_PASSWORD` first (see `.env.example`), or run
`flask --app app create-admin yourname`.

Run the tests (72 checks, temporary database): `python tests.py`

## Uploads

Each document: PDF, JPG or PNG, up to 2 MB, one file per document type. Several files can be saved in one
step (up to about 13 MB in a single request). Every other form is limited to 64 KB. Files are stored inside
the database, so a backup contains them.

## Staying signed in on Render

Set `SECRET_KEY` (the Blueprint does this for you). If the key changes, every browser is signed out, which
happens on each deploy when the key is not set.

## Upgrading from an earlier version

Replace the files and restart. The database upgrades itself on start (new tables and columns are
added; nothing is deleted). Your existing staff account becomes an Administrator.

## Deploy on Render

1. Put this folder in a GitHub repository (`instance/` and `.env` are in `.gitignore`).
2. On Render choose **New > Blueprint** and select the repository. `render.yaml` does the rest.
3. Type a strong `ADMIN_PASSWORD` when asked. `SECRET_KEY` is generated.
4. Open the URL; `/healthz` should say `ok`.

**Important: data storage.** Applications, accounts *and uploaded documents* live in one SQLite file.
Render's free plan has a temporary disk, so that file is erased on every restart or deploy. For real
use, attach a persistent disk (see `render.yaml`) and set `DATABASE_PATH=/var/data/miutm.db`, or move
to PostgreSQL (`db.py` is the only file that talks to the database). Download backups from the staff
sidebar regularly. A backup is one `.db` file you can open with "DB Browser for SQLite".

## Turning on email (optional)

Email is off until you set these variables. Without them the site works normally and tells people
not to expect emails. With them: application confirmations, status updates, ticket updates, message
replies and password reset links are sent.

| Variable | Example |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `yourname@gmail.com` |
| `SMTP_PASSWORD` | a Gmail *app password*, not your normal password |
| `SMTP_FROM` | `MIUTM <yourname@gmail.com>` |
| `SMTP_TLS` | `1` |

## All settings

| Name | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs cookies and reset links | random, saved in `instance/secret_key` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | First administrator (only if no staff exist) | `admin`, generated |
| `DATABASE_PATH` | SQLite file location | `instance/miutm.db` |
| `DEMO_MODE` | Show the demonstration ribbon | `1` |
| `ALLOW_INDEXING` | Let search engines index the site | `0` |
| `ADMISSIONS_FORCE_OPEN` | Keep the form open after the closing date | `0` |
| `SESSION_DAYS` | How long a signed-in browser stays signed in after its last visit | `90` |
| `STAFF_SIGNUP_CODE` | If set, the Admin register form asks for this code | none |
| `SMTP_*` | Email (above) | off |

## Where to edit things

* `site_data.py`: contact details, admission dates (change yearly), team, About page text,
  statuses, document types, scholarship text.
* **Staff area > Website content**: programmes, notices, events, faculty, FAQs. No code needed.
* `static/css/site.css`: colours and fonts are variables at the top.

## Files

```
app.py            setup and public routes          student.py   student accounts and dashboard
admin.py          staff area (core)                admin_more.py content manager, staff, reports, backup
db.py             schema, upgrades, starter data   workflow.py   status changes and seat counts
validators.py     every form check                 mailer.py     optional email
security.py       CSRF, rate limits, sign-in guards, headers      audit.py   activity log
site_data.py      shared facts and text            tests.py      47 automated checks
templates/ static/ render.yaml Procfile requirements.txt .env.example
```

## Security notes

CSRF tokens on every POST, hashed passwords, rate-limited logins, sessions that expire after 2 hours,
staff accounts re-checked on every request (disabling one takes effect immediately), staff
registration that needs an administrator's approval, uploads checked
by type, size and file content and never served inline, a strict Content-Security-Policy, and an
activity log. The rate limiter is per process; use Redis or Flask-Limiter if you run many servers.

## Not built (needs outside services or real data)

Online fee payment, SMS/WhatsApp alerts, entrance-exam registration and hall tickets, a faculty
portal, attendance and results, a library catalogue, alumni network, Hindi language support, and a
placements page (add one only when there is real data). Names, faculty, fees, seats and dates are sample data.
