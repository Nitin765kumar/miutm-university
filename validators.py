"""
validators.py - server-side checks for every form.

Browsers also validate (see the HTML attributes), but that can be bypassed, so the
server never trusts it. Each function returns (clean_values, errors) where errors maps a
field name to a message the person can act on.
"""
import re
from datetime import datetime

import site_data

NAME_RE = re.compile(r"^[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F .'\-]{1,79}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
PIN_RE = re.compile(r"^[1-9]\d{5}$")


def _clean(form, key, limit=500):
    value = (form.get(key) or "").strip()
    # collapse inner whitespace for single-line fields
    return re.sub(r"\s+", " ", value)[:limit]


def normalise_phone(raw):
    digits = re.sub(r"[\s\-()]", "", raw or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


def _name(form, key, label, errors, values):
    value = _clean(form, key, 80)
    values[key] = value
    if not value:
        errors[key] = f"Enter {label}."
    elif not NAME_RE.match(value):
        errors[key] = f"{label[0].upper() + label[1:]} can only contain letters, spaces, dots, hyphens and apostrophes (2 to 80 characters)."


def validate_application(form, course):
    """
    form   - request.form (or any mapping)
    course - the sqlite Row for the chosen programme, or None if it was not found
    """
    errors, v = {}, {}

    _name(form, "full_name", "your full name", errors, v)
    _name(form, "father_name", "your father's name", errors, v)
    _name(form, "mother_name", "your mother's name", errors, v)

    # date of birth
    v["dob"] = _clean(form, "dob", 10)
    try:
        born = datetime.strptime(v["dob"], "%Y-%m-%d").date()
        today = site_data.today_ist()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if born > today:
            errors["dob"] = "Date of birth cannot be in the future."
        elif age < 14 or age > 70:
            errors["dob"] = "Enter a valid date of birth (age 14 to 70)."
    except ValueError:
        errors["dob"] = "Enter your date of birth."

    v["gender"] = _clean(form, "gender", 20)
    if v["gender"] not in site_data.GENDERS:
        errors["gender"] = "Choose a gender option."

    v["category"] = _clean(form, "category", 20)
    if v["category"] and v["category"] not in site_data.CATEGORIES:
        errors["category"] = "Choose a category from the list, or leave it blank."

    v["nationality"] = _clean(form, "nationality", 40) or "Indian"
    if not re.match(r"^[A-Za-z][A-Za-z .\-]{1,39}$", v["nationality"]):
        errors["nationality"] = "Enter a valid nationality."

    v["email"] = _clean(form, "email", 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address, like name@example.com."

    v["phone"] = normalise_phone(_clean(form, "phone", 20))
    if not PHONE_RE.match(v["phone"]):
        errors["phone"] = "Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9."

    v["qualification"] = _clean(form, "qualification", 40)
    if v["qualification"] not in site_data.QUALIFICATIONS:
        errors["qualification"] = "Choose your highest completed qualification."

    raw_pct = _clean(form, "percentage", 8)
    v["percentage"] = raw_pct
    try:
        pct = round(float(raw_pct), 1)
        if not (0 < pct <= 100):
            raise ValueError
        v["percentage"] = pct
    except ValueError:
        errors["percentage"] = "Enter your percentage between 1 and 100. Convert CGPA to percentage first."
        pct = None

    v["course_code"] = _clean(form, "course_code", 20)
    if course is None:
        errors["course_code"] = "Choose the programme you are applying for."
    else:
        # Rules taken from the programme's own eligibility
        accepted = [a.strip() for a in course["accepts"].split(",")]
        q = v["qualification"]
        if q in site_data.QUALIFICATIONS and q != "Other" and q not in accepted:
            errors["qualification"] = (
                f"{course['name']} accepts: {', '.join(accepted)}. "
                "Choose \u201cOther\u201d if your qualification is equivalent."
            )
        if pct is not None and course["min_percent"] and pct < course["min_percent"]:
            errors["percentage"] = (
                f"{course['name']} needs at least {course['min_percent']}% marks."
            )

    v["address"] = _clean(form, "address", 200)
    if not (5 <= len(v["address"]) <= 200):
        errors["address"] = "Enter your permanent address (5 to 200 characters)."

    v["city"] = _clean(form, "city", 60)
    if not re.match(r"^[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F .'\-]{1,59}$", v["city"]):
        errors["city"] = "Enter your city or town."

    v["state"] = _clean(form, "state", 60)
    if v["state"] not in site_data.STATES:
        errors["state"] = "Choose your state or union territory."

    v["pincode"] = _clean(form, "pincode", 6)
    if not PIN_RE.match(v["pincode"]):
        errors["pincode"] = "Enter a valid 6-digit PIN code."

    if form.get("declaration") != "yes":
        errors["declaration"] = "Tick the declaration to submit your application."

    return v, errors


def validate_contact(form):
    errors, v = {}, {}

    v["name"] = _clean(form, "name", 80)
    if len(v["name"]) < 2:
        errors["name"] = "Enter your name."

    v["email"] = _clean(form, "email", 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address."

    raw_phone = _clean(form, "phone", 20)
    v["phone"] = normalise_phone(raw_phone) if raw_phone else ""
    if v["phone"] and not PHONE_RE.match(v["phone"]):
        errors["phone"] = "Enter a 10-digit mobile number, or leave this blank."

    v["department"] = _clean(form, "department", 40)
    if v["department"] not in [d["key"] for d in site_data.DEPARTMENTS]:
        errors["department"] = "Choose who should receive your message."

    v["subject"] = _clean(form, "subject", 120)
    if len(v["subject"]) < 3:
        errors["subject"] = "Add a short subject (at least 3 characters)."

    # message keeps line breaks
    message = (form.get("message") or "").strip()
    message = re.sub(r"[ \t]+", " ", message)[:2000]
    v["message"] = message
    if len(message) < 10:
        errors["message"] = "Write at least 10 characters so we can help."

    return v, errors


def validate_status_update(form):
    errors, v = {}, {}
    v["status"] = _clean(form, "status", 20)
    if v["status"] not in site_data.STATUSES:
        errors["status"] = "Choose a valid status."
    v["note"] = _clean(form, "note", 400)
    v["remarks"] = (form.get("remarks") or "").strip()[:1000]
    return v, errors


def validate_new_password(current_ok, new, confirm):
    errors = {}
    if not current_ok:
        errors["current"] = "Current password is incorrect."
    if len(new) < 10:
        errors["new"] = "Use at least 10 characters."
    elif new.lower() == new or new.upper() == new or not any(c.isdigit() for c in new):
        errors["new"] = "Mix upper and lower case letters and include a number."
    if new != confirm:
        errors["confirm"] = "The two passwords do not match."
    return errors


# ---------------------------------------------------------------------------
# Student accounts, tickets, staff, uploads, content
# ---------------------------------------------------------------------------
import os  # noqa: E402
from datetime import date as _date  # noqa: E402

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")


def student_password_errors(password):
    if len(password) < 8:
        return "Use at least 8 characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Include at least one letter and one number."
    return None


def validate_student_register(form):
    errors, v = {}, {}
    _name(form, "full_name", "your full name", errors, v)
    v["email"] = _clean(form, "email", 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address."
    raw = _clean(form, "phone", 20)
    v["phone"] = normalise_phone(raw) if raw else ""
    if v["phone"] and not PHONE_RE.match(v["phone"]):
        errors["phone"] = "Enter a 10-digit mobile number, or leave this blank."
    password, confirm = form.get("password") or "", form.get("confirm") or ""
    problem = student_password_errors(password)
    if problem:
        errors["password"] = problem
    elif password != confirm:
        errors["confirm"] = "The two passwords do not match."
    return v, errors


def validate_profile(form):
    errors, v = {}, {}
    _name(form, "full_name", "your full name", errors, v)
    raw = _clean(form, "phone", 20)
    v["phone"] = normalise_phone(raw) if raw else ""
    if v["phone"] and not PHONE_RE.match(v["phone"]):
        errors["phone"] = "Enter a 10-digit mobile number, or leave this blank."
    return v, errors


def validate_student_password_change(current_ok, new, confirm):
    errors = {}
    if not current_ok:
        errors["current"] = "Current password is incorrect."
    problem = student_password_errors(new)
    if problem:
        errors["new"] = problem
    elif new != confirm:
        errors["confirm"] = "The two passwords do not match."
    return errors


def validate_ticket(form):
    errors, v = {}, {}
    v["name"] = _clean(form, "name", 80)
    if len(v["name"]) < 2:
        errors["name"] = "Enter your name."
    v["email"] = _clean(form, "email", 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address."
    raw = _clean(form, "phone", 20)
    v["phone"] = normalise_phone(raw) if raw else ""
    if v["phone"] and not PHONE_RE.match(v["phone"]):
        errors["phone"] = "Enter a 10-digit mobile number, or leave this blank."
    v["category"] = _clean(form, "category", 60)
    if v["category"] not in site_data.TICKET_CATEGORIES:
        errors["category"] = "Choose what your message is about."
    v["subject"] = _clean(form, "subject", 120)
    if len(v["subject"]) < 3:
        errors["subject"] = "Add a short subject."
    message = re.sub(r"[ \t]+", " ", (form.get("message") or "").strip())[:3000]
    v["message"] = message
    if len(message) < 15:
        errors["message"] = "Describe the problem in at least 15 characters."
    return v, errors


def validate_staff(form, creating, existing_username=None):
    errors, v = {}, {}
    v["username"] = (existing_username if not creating else _clean(form, "username", 30).lower())
    if creating and not USERNAME_RE.match(v["username"]):
        errors["username"] = "3 to 30 characters: lower-case letters, numbers, dot, dash or underscore."
    v["full_name"] = _clean(form, "full_name", 80)
    if len(v["full_name"]) < 2:
        errors["full_name"] = "Enter the person's name."
    v["email"] = _clean(form, "email", 120).lower()
    if v["email"] and not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address, or leave it blank."
    v["role"] = _clean(form, "role", 20)
    if v["role"] not in site_data.ROLES:
        errors["role"] = "Choose a role."
    v["is_active"] = 1 if form.get("is_active") == "1" else 0
    if creating:
        pw = form.get("password") or ""
        if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
            errors["password"] = "At least 10 characters, with upper and lower case letters and a number."
    return v, errors


# ---- uploads ----------------------------------------------------------------
MAGIC = {"application/pdf": (b"%PDF-",), "image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",)}


def check_upload(file_storage, doc_type):
    """Returns (data, mime, filename, error). Checks type, size and the file's real content."""
    if doc_type not in site_data.DOC_TYPES:
        return None, None, None, "Choose which document you are uploading."
    if file_storage is None or not file_storage.filename:
        return None, None, None, "Choose a file to upload."
    from werkzeug.utils import secure_filename
    name = secure_filename(file_storage.filename) or doc_type.replace(" ", "-").lower()
    ext = os.path.splitext(name)[1].lower()
    mime = site_data.DOC_EXTENSIONS.get(ext)
    if not mime:
        return None, None, None, "Only PDF, JPG and PNG files are accepted."
    data = file_storage.read(site_data.DOC_MAX_BYTES + 1)
    if not data:
        return None, None, None, "That file is empty."
    if len(data) > site_data.DOC_MAX_BYTES:
        return None, None, None, "The file is larger than 2 MB."
    if not any(data.startswith(sig) for sig in MAGIC[mime]):
        return None, None, None, "The file's content does not match its type. Upload a real PDF, JPG or PNG."
    return data, mime, name[:120], None


# ---- generic content forms (programmes, notices, events, faculty, FAQs) ------
def parse_content_field(f, raw, editing):
    """f is a field spec dict from content_admin.CONTENT. Returns (value, error)."""
    kind = f["type"]
    label = f["label"]
    if kind == "bool":
        return (1 if raw == "1" else 0), None
    raw = re.sub(r"[ \t]+", " ", (raw or "").strip()) if kind != "textarea" else (raw or "").strip()
    if f.get("readonly_on_edit") and editing:
        return None, None
    if not raw:
        if f.get("required", True):
            return None, f"Enter {label.lower()}."
        return None, None
    if kind in ("text", "textarea"):
        limit = f.get("max", 200)
        if len(raw) > limit:
            return None, f"{label} must be {limit} characters or fewer."
        return raw, None
    if kind == "int":
        try:
            n = int(raw)
        except ValueError:
            return None, f"{label} must be a whole number."
        if not (f.get("min", 0) <= n <= f.get("max", 10**9)):
            return None, f"{label} must be between {f.get('min', 0)} and {f.get('max', 10**9)}."
        return n, None
    if kind == "date":
        try:
            _date.fromisoformat(raw)
        except ValueError:
            return None, f"Enter a valid date for {label.lower()}."
        return raw, None
    if kind == "select":
        if raw not in f["choices"]:
            return None, f"Choose a valid option for {label.lower()}."
        return raw, None
    return None, "Unsupported field."


def validate_staff_registration(form, required_code=""):
    """Public 'Admin register' form. The account is created disabled and waits for an administrator."""
    errors, v = {}, {}
    v["username"] = _clean(form, "username", 30).lower()
    if not USERNAME_RE.match(v["username"]):
        errors["username"] = "3 to 30 characters: lower-case letters, numbers, dot, dash or underscore."
    v["full_name"] = _clean(form, "full_name", 80)
    if len(v["full_name"]) < 2:
        errors["full_name"] = "Enter your full name."
    v["email"] = _clean(form, "email", 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "Enter a valid email address."
    pw, confirm = form.get("password") or "", form.get("confirm") or ""
    if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        errors["password"] = "At least 10 characters, with upper and lower case letters and a number."
    elif pw != confirm:
        errors["confirm"] = "The two passwords do not match."
    if required_code:
        import hmac
        if not hmac.compare_digest((form.get("access_code") or "").strip(), required_code):
            errors["access_code"] = "That access code is not correct. Ask an administrator for it."
    return v, errors
