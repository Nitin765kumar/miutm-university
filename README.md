# MIUTM Portal, version 5

The website and admission system for Maurya International University of Technology & Management (a demonstration
institution). Python 3.12, Flask, **PostgreSQL in production** (SQLite for local development), plain CSS and JavaScript.

## What is new in version 5

| Area | What changed |
|---|---|
| Database | PostgreSQL through one `DATABASE_URL` setting; versioned migrations; foreign keys, indexes and unique rules; transactions; a self-check (`flask db-check`) |
| Persistence | Data lives in PostgreSQL, so restarts and redeploys no longer erase it (see the warning about free plans below) |
| Backups | One-file backup of every table (documents, payments, accounts, logs), a command to restore it, and an automated restore test |
| Duplicates | The database allows one live application per student, programme and session. A double click cannot create two |
| Passwords | Show/hide eye on every password field, strength meter with the requirements, "passwords do not match" message, staff password reset by email, email verification for students |
| Courses | A full page per programme; semester-wise syllabus with codes, credits, theory/practical type and units for all 10 programmes (230 subjects); view online and download as PDF |
| Payments | Application fee and admission fee, payment page, success and failure handling, safe retry, receipts (PDF), history, staff payment management, export, refunds. A **demonstration gateway**: no money moves |
| Workflow | 12 statuses, history with who and when, rejection reasons, timeline, merit ranks, publication, waitlist that promotes itself |
| Documents | Pending / Verified / Rejected with a reason, who reviewed and when, full history |
| Notifications | Notification centre in the app, email delivery log with Sent / Failed / Retrying and a retry button |
| Staff | Statistics, filters (programme, status, payment, documents, session, dates), bulk actions (export, verify documents, change status), all audited |
| Public | Fee structure, academic calendar, admission guidelines, refund policy, documents required, downloads (prospectus, fees, syllabus), merit-list search |
| Quality | Friendly inline form messages, loading states, 403/404/413/429/500/503 pages with a reference number, structured logs that never hold private data |

## Run it on your computer

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug        # http://127.0.0.1:5000  (uses a local SQLite file)
```

On the first start the terminal prints the administrator's password once. Sign in at `/admin`, then change it under
My profile. To choose it yourself, set `ADMIN_USERNAME` and `ADMIN_PASSWORD` before the first start.
Run the tests with `python tests.py`.

## PostgreSQL (production)

### The one thing to know first

**Render's own free PostgreSQL is deleted 30 days after it is created.** It is fine for a trial and wrong for data you
want to keep. For lasting data use one of:

| Choice | Notes |
|---|---|
| Render PostgreSQL, a paid plan | Simplest on Render: the database sits next to the site and keeps its data |
| A free permanent PostgreSQL from Neon or Supabase | Works with this site through the same `DATABASE_URL`; free-plan limits and sleeping rules change, so read the provider's pricing page |

The web service on Render's free plan still sleeps when idle and has no disk, but that no longer matters for data: the
data is in the database.

### Steps

1. Create the database with your chosen provider and copy its **connection string**. It looks like
   `postgresql://user:password@host:5432/dbname?sslmode=require`.
2. In Render open the service, **Environment**, add `DATABASE_URL` with that value, and save. Never put it in the code or in git.
3. Test it from your computer before deploying (use the provider's *external* address):
   ```bash
   export DATABASE_URL='postgresql://...'      # Windows PowerShell: $env:DATABASE_URL='postgresql://...'
   flask --app app db-check
   ```
   Every line should say PASS: connection, tables, migrations, data types (binary, number, date, time), row ids and
   rollback, unique rules, the duplicate-application rule, and search. If a line says FAIL, send that line to whoever
   maintains the site; it names the problem.
4. Deploy. The first start creates every table, adds the starter programmes and the 230-subject syllabus, and creates
   the administrator. `/healthz` now reports `"database": "postgresql"`.
5. **Prove it persists:** submit a test application, then on Render choose *Manual Deploy* and redeploy. The application
   must still be there. The staff dashboard also warns you in red if the site is on Render but not using PostgreSQL.

### Moving your existing version 4 data

Your deployed version 4 kept its data in a SQLite file that Render erases on restart, so only data you saved
elsewhere can be moved. Download a backup from the old staff area ("Download backup" gives a `.db` file), then:

```bash
export DATABASE_URL='postgresql://...'
flask --app app import-sqlite path/to/miutm-backup.db --yes
```

This copies every table, converts the old status names (Pending to Submitted, Enrolled to Admission Confirmed, Uploaded
to Pending) and marks old applications as "Waived" for the application fee. It **replaces** what is in the target database.

### What was and was not tested

The PostgreSQL code was written to the same SQL as the SQLite code and tested as far as is possible without a PostgreSQL
server: the engine-specific translation (placeholders, `now()`, `RETURNING id`, row objects), the PostgreSQL table
definitions, and a scan that every SQL statement the app ran is portable. **It has not been run against a real
PostgreSQL server in the development environment.** `flask db-check` (step 3) is how you confirm it on yours, and it
should be the first thing you run.

## Backups and restore

* **Staff area:** the *Download backup* button (administrators) gives one `.json.gz` file with every table, including the
  uploaded documents and payments. Take one before every update and at the end of each admission cycle.
* **Command line:**
  ```bash
  flask --app app backup -o miutm-backup.json.gz       # write a backup
  flask --app app restore miutm-backup.json.gz --yes   # replace EVERYTHING with a backup
  ```
* A backup from SQLite restores into PostgreSQL and the other way round.
* **Test your restore** before you need it: restore a backup into a spare database and compare the application count.
  The automated tests do exactly this and also check that documents come back byte for byte.
* Keep backups private: they contain personal data and password hashes.
* Paid PostgreSQL plans usually include the provider's own backups too. Check your provider.

## Commands

`flask --app app <command>`

| Command | Use |
|---|---|
| `db-check` | Test the connection and everything the site depends on |
| `backup [-o FILE]` | Write a full backup |
| `restore FILE [--yes]` | Replace the whole database with a backup |
| `import-sqlite FILE [--yes]` | Copy a version 4 SQLite file into the current database |
| `create-admin USERNAME` | Create an administrator, or reset a password and re-enable the account |
| `list-staff` | Show staff accounts and which database is in use |
| `retry-emails` | Try the failed emails again |
| `security-check` | Check the configuration and look for secrets left in the source files |

## Settings (environment variables)

| Name | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL address. Empty means local SQLite | empty |
| `DATABASE_PATH` | SQLite file, used only when `DATABASE_URL` is empty | `instance/miutm.db` |
| `DB_POOL_MAX` | Connections each server process keeps to PostgreSQL | `10` |
| `SECRET_KEY` | Signs cookies and links. Set it, or every deploy signs everyone out | random file |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | The first administrator (first start only) | `admin`, generated |
| `SESSION_DAYS` | Days a signed-in browser stays signed in | `90` |
| `STAFF_SIGNUP_CODE` | If set, the Admin register page asks for it | none |
| `DEMO_MODE` | Shows the demonstration notice and the "simulate a failed payment" option | `1` |
| `ALLOW_INDEXING` | Let search engines index the site | `0` |
| `ADMISSIONS_FORCE_OPEN` | Keep applications open outside the dates | `0` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | Email. Off unless `SMTP_HOST` is set | off |

Dates, contact details and the **application fee** are changed in the browser under *Site settings* (administrators).
The admission fee of each programme is in *Website content, Programmes*.

## The admission process

1. A student creates an account (email confirmation is required when email is switched on) and fills the five-step form
   (details, contact, education, documents, review). Progress is saved as a draft at every step.
2. **Submit** creates the application with status *Payment Pending* and opens the payment page for the application fee.
   With no fee set, it goes straight to *Submitted*.
3. A successful payment records a transaction, submits the application, creates a receipt and notifies the student.
   A failed payment leaves it saved; retrying reuses the same order, so there is never a second application or a second charge.
4. Staff verify documents and review. Rejecting a document or an application needs a reason, which the student sees.
5. The administrator runs the **merit list**: applicants who paid are ranked by marks (then by who applied first), the
   top ones for the free seats become *Selected*, the rest *Waitlisted*. Publishing makes the ranks searchable on the
   public Merit lists page (application number and rank only).
6. A selected student pays the **admission fee**, which sets the status to *Approved* and unlocks the admission letter.
   After counselling staff set *Admission Confirmed*, which unlocks the confirmation letter.
7. When a selected, approved or confirmed student leaves (cancels or is rejected), the best-ranked waitlisted applicant
   is selected automatically and told.

| Status | Holds a seat | Student can edit |
|---|---|---|
| Payment Pending | no | yes |
| Submitted | no | yes |
| Under Review, Documents Verification, Merit Evaluation | no | no |
| Selected, Admission Fee Pending, Approved, Admission Confirmed | **yes** | no |
| Waitlisted | no | no |
| Rejected, Cancelled | no (and a new application is allowed) | no |

**Duplicate rule:** one live application per student, programme and session, enforced by the database. A student may apply
to different programmes. After a Cancelled or Rejected application they may apply to the same programme again.

## Payments

This version has a **demonstration gateway** (`payments.py`, function `run_demo`). It never asks for card or bank details
and no money moves. The page offers UPI, Card, Net Banking and Demo Payment, and (in demo mode) a switch to simulate a failure.

To use a real provider later you only replace `run_demo`: create an order with the provider, send the student to its
secure page, and when the provider's **signed** confirmation arrives call `payments.succeed()` (or `payments.fail()`).
Everything else, the order, the states (Pending, Processing, Successful, Failed, Cancelled, Refunded), the records, the
receipts, the admin pages and the refund screen, stays as it is. Real payments also need a business the provider has
verified and a published refund policy, which a demonstration institution cannot have.

## Syllabus and downloads

Every programme page has the overview, duration, eligibility, admission process, fee structure, total credits, career
opportunities, outcomes, documents required, and the semester-wise syllabus with **View syllabus** and
**Download syllabus PDF**. Public downloads: prospectus, fee structure and a syllabus for each programme. Students also get
an application receipt, payment receipts, an admission letter and a confirmation letter. All PDFs are generated by the site.
The syllabus is sample content, stored in the database after the first start.

## Security and privacy

* Passwords are hashed; CSRF protection on every form; strict Content-Security-Policy; sessions are HttpOnly, SameSite and
  Secure on the hosted site; sign-ins for staff and students are independent.
* Every staff page checks the role on the server. Students see only their own applications, payments and documents.
* Uploads are checked by type, size and content. The payment page never collects card details.
* **Logs** are one JSON line each with a request number. They never contain passwords, tokens, email addresses, form data
  or the text of an error message, because database errors can quote private values. Database, email, payment and file
  failures are logged under their own names.
* `flask security-check` looks at the configuration and scans the source for secrets. If any password or key was ever
  committed or shared, **change it**: removing it from the code does not undo the exposure.
* Not covered: two-step sign-in, encryption of documents at rest, malware scanning of uploads, and a formal data-protection review.

## Tests

`python tests.py` runs 120 checks on a temporary database. They cover the database layer, backup and restore (including
document bytes), import from a version 4 file, a six-process start-up race, the PostgreSQL translation logic, a scan that
every SQL statement is portable, accounts and passwords, the whole application flow, payments (success, failure, retry,
double click, refund), the merit list and waitlist, documents, notifications, every public page and PDF, staff tools,
email failures, logging safety, error pages and security.

## Deploying on Render

1. Put the project on GitHub.
2. On Render choose **New, Blueprint**, pick the repository, and type `ADMIN_PASSWORD` when asked.
3. Add `DATABASE_URL` (see above), then open `/healthz` and run the persistence check from step 5.

## Files

`app.py` public pages, errors, commands · `apply_flow.py` the application · `student.py` student area · `admin.py`,
`admin_more.py` staff area · `db.py` connections, migrations, start-up · `schema.py` the tables · `dbtools.py` backup,
restore, import, self-check · `payments.py` fees · `workflow.py` statuses, merit, waitlist · `notify.py`, `mailer.py`
notifications and email · `pdfdocs.py` PDFs · `syllabus_data.py` programme content · `logsetup.py` logging ·
`security.py`, `validators.py`, `settings.py`, `site_data.py`, `seed_data.py`, `audit.py` · `templates/`, `static/` ·
`render.yaml`, `Procfile`, `requirements.txt`, `.env.example` · `tests.py`.
