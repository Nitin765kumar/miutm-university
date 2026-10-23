"""
site_data.py - the one place to edit facts that appear on several pages.

Contact details, admission dates, team members and the demo notice all live here,
so they can never disagree between the Home, About, Contact and Admission pages.
Programmes, notices and faculty live in the database (see db.py).
"""
import os
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def today_ist():
    """Today's date in India, whatever timezone the server runs in."""
    return datetime.now(IST).date()


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Switches (set these as environment variables on your host)
# ---------------------------------------------------------------------------
# Shows the "demonstration project" ribbon on every public page.
DEMO_MODE = env_flag("DEMO_MODE", True)
# Search engines are told NOT to index the site unless you set ALLOW_INDEXING=1.
ALLOW_INDEXING = env_flag("ALLOW_INDEXING", False)
# Keeps the application form open even after the closing date below.
ADMISSIONS_FORCE_OPEN = env_flag("ADMISSIONS_FORCE_OPEN", False)

# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------
SITE = {
    "name": "Maurya International University of Technology & Management",
    "short": "MIUTM",
    "tagline": "Computing, engineering and management, taught by doing.",
    "address": ["MIUTM Campus", "Riverside Academic Zone", "Ayodhya, Uttar Pradesh \u2013 224001"],
    "phone": "+91 98765 43210",
    "phone_alt": "+91 94500 12345",
    "hours": "Monday to Saturday, 9:00 am to 5:00 pm",
    "general_email": "info@miutm.edu.in",
    "maps_url": "https://www.google.com/maps/search/?api=1&query=Ayodhya%2C+Uttar+Pradesh",
    "demo_notice": (
        "Demonstration project. MIUTM is not a real institution; names, figures "
        "and contact details on this site are sample data."
    ),
    "project_credit": (
        "Built by Nitin Kumar and Rishikant as a BCA major project (session 2025\u201326) "
        "at K.S. Saket P.G. College, Ayodhya."
    ),
}

# Used by the contact form dropdown and the department directory.
DEPARTMENTS = [
    {"key": "Admissions Office", "email": "admissions@miutm.edu.in",
     "about": "Eligibility, counselling, scholarships and application help."},
    {"key": "Registrar Office", "email": "registrar@miutm.edu.in",
     "about": "Certificates, student verification and records."},
    {"key": "Examination Cell", "email": "exams@miutm.edu.in",
     "about": "Semester exams, admit cards and results."},
    {"key": "Placement Cell", "email": "placements@miutm.edu.in",
     "about": "Internships, recruitment and employer relations."},
    {"key": "Finance Office", "email": "finance@miutm.edu.in",
     "about": "Fees, refunds and scholarship payments."},
    {"key": "Research Centre", "email": "research@miutm.edu.in",
     "about": "Projects, patents and collaborations."},
    {"key": "International Office", "email": "international@miutm.edu.in",
     "about": "International admissions, exchange and visa guidance."},
    {"key": "IT Help Desk", "email": "itsupport@miutm.edu.in",
     "about": "Portal access, email and software support."},
]

# ---------------------------------------------------------------------------
# Admission cycle - edit these dates each year
# ---------------------------------------------------------------------------
CYCLE = {
    "session": "2027\u201328",
    "milestones": [
        {"key": "opens", "label": "Applications open", "date": date(2026, 10, 1),
         "note": "Apply online and get your application number at once."},
        {"key": "closes", "label": "Applications close", "date": date(2027, 4, 30),
         "note": "Last day to submit the online form."},
        {"key": "merit", "label": "Merit list published", "date": date(2027, 5, 15),
         "note": "Check your status with the tracker."},
        {"key": "counselling", "label": "Counselling and seat confirmation", "date": date(2027, 6, 1),
         "note": "Bring original documents for verification."},
        {"key": "classes", "label": "Classes begin", "date": date(2027, 8, 2),
         "note": "Orientation week for new students."},
    ],
}


# ---------------------------------------------------------------------------
# Settings that staff can change in the browser override the defaults above.
# settings.py loads them into flask.g at the start of every request.
# ---------------------------------------------------------------------------
def staff_signup_code():
    """If set, the staff registration form asks for this code (keeps strangers out)."""
    return os.environ.get("STAFF_SIGNUP_CODE", "").strip()


def build_site(over):
    site = dict(SITE)
    for key in ("phone", "phone_alt", "hours", "general_email"):
        if over.get(key):
            site[key] = over[key]
    lines = [over.get(f"address{i}") for i in (1, 2, 3)]
    if any(lines):
        site["address"] = [x for x in lines if x]
    return site


def build_cycle(over):
    milestones = []
    for m in CYCLE["milestones"]:
        item = dict(m)
        raw = over.get(m["key"])
        if raw:
            try:
                item["date"] = date.fromisoformat(raw)
            except ValueError:
                pass
        milestones.append(item)
    return {"session": over.get("session") or CYCLE["session"], "milestones": milestones}


def _ctx(name, default):
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, name):
            return getattr(g, name)
    except Exception:  # outside Flask (tests, scripts)
        pass
    return default


def current_site():
    return _ctx("site", SITE)


def current_cycle():
    return _ctx("cycle", CYCLE)


def force_open():
    return ADMISSIONS_FORCE_OPEN or bool(_ctx("force_open", False))


def admission_window(cycle=None):
    cycle = cycle or current_cycle()
    opens = next(m["date"] for m in cycle["milestones"] if m["key"] == "opens")
    closes = next(m["date"] for m in cycle["milestones"] if m["key"] == "closes")
    return opens, closes


def admissions_state(today=None, cycle=None):
    """Returns 'upcoming', 'open' or 'closed'."""
    today = today or today_ist()
    opens, closes = admission_window(cycle)
    if force_open():
        return "open"
    if today < opens:
        return "upcoming"
    if today > closes:
        return "closed"
    return "open"


def timeline(today=None, cycle=None):
    """Milestones with a state: done / next / later."""
    today = today or today_ist()
    cycle = cycle or current_cycle()
    items, found_next = [], False
    for m in cycle["milestones"]:
        item = dict(m)
        if m["date"] < today:
            item["state"] = "done"
        elif not found_next:
            item["state"] = "next"
            found_next = True
        else:
            item["state"] = "later"
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Team (shown on the About page)
# ---------------------------------------------------------------------------
TEAM = [
    {"name": "Nitin Kumar", "role": "Founder and Director, IT", "photo": "img/team/nitin.webp",
     "bio": "Leads the university's digital systems and technology programmes.",
     "links": {"GitHub": "https://github.com/Nitin765kumar",
               "LinkedIn": "https://www.linkedin.com/in/nitinkumar25"}},
    {"name": "Rishikant", "role": "Technical Coordinator", "photo": "img/team/rishikant.webp",
     "bio": "Plans technical projects and looks after infrastructure."},
    {"name": "Anish Bhaskar", "role": "Research Coordinator", "photo": "img/team/anish.webp",
     "bio": "Supports research programmes and interdisciplinary work."},
    {"name": "Shailendra Pal", "role": "Administrative Coordinator", "photo": "img/team/shailendra.webp",
     "bio": "Coordinates administration and student services."},
]

DEVELOPER_LINKS = {
    "GitHub": "https://github.com/Nitin765kumar",
    "LinkedIn": "https://www.linkedin.com/in/nitinkumar25",
    "YouTube": "https://www.youtube.com/@nitinkumar8487",
}

# ---------------------------------------------------------------------------
# Form choices
# ---------------------------------------------------------------------------
GENDERS = ["Male", "Female", "Other"]
CATEGORIES = ["General", "OBC", "SC", "ST", "EWS"]
QUALIFICATIONS = ["12th (Intermediate)", "Diploma", "Bachelor's degree", "Master's degree", "Other"]

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh",
    "Lakshadweep", "Puducherry",
]

STATUSES = ["Pending", "Under Review", "Approved", "Waitlisted", "Enrolled", "Rejected", "Cancelled"]
# Statuses in which a student may still withdraw. After Rejected, Cancelled or Enrolled it is final.
WITHDRAWABLE = ["Pending", "Under Review", "Approved", "Waitlisted"]
# Statuses that use up a seat.
SEAT_STATUSES = ["Approved", "Enrolled"]

# Plain-language meaning of each status, shown to applicants.
STATUS_HELP = {
    "Pending": "Your application has been received and is waiting for review.",
    "Under Review": "The admission office is checking your details and documents.",
    "Approved": "Your application is approved. Download your offer letter and follow the counselling steps to confirm your seat.",
    "Waitlisted": "All seats are filled for now. You are on the waiting list and will be told if a seat opens.",
    "Enrolled": "Your admission is confirmed. Welcome to MIUTM.",
    "Rejected": "Your application was not accepted this time. Contact the admissions office for details.",
    "Cancelled": "This application was cancelled, so it is closed and its seat is released.",
}

# What the student should do next, by status.
STATUS_NEXT = {
    "Pending": "Upload your documents so the office can start verification.",
    "Under Review": "Keep your original documents ready for counselling.",
    "Approved": "Download your offer letter and attend counselling with original documents.",
    "Waitlisted": "No action needed. We will contact you if a seat opens.",
    "Enrolled": "Watch your email and notices for orientation details.",
    "Rejected": "You may apply to another programme while applications are open.",
    "Cancelled": "You may submit a new application while applications are open.",
}

# ---------------------------------------------------------------------------
# Staff, documents, support
# ---------------------------------------------------------------------------
ROLES = {"admin": "Administrator", "reviewer": "Reviewer"}

DOC_TYPES = ["Class 10 marksheet", "Class 12 marksheet", "Degree or diploma marksheet",
             "Passport-size photo", "Category certificate", "Transfer certificate"]
DOC_STATUSES = ["Uploaded", "Verified", "Rejected"]
DOC_MAX_BYTES = 2 * 1024 * 1024
DOC_EXTENSIONS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def required_docs(qualification, category):
    """Documents an applicant must upload, depending on their own answers."""
    need = ["Class 10 marksheet", "Class 12 marksheet", "Passport-size photo"]
    if qualification in ("Diploma", "Bachelor's degree", "Master's degree"):
        need.append("Degree or diploma marksheet")
    if category and category != "General":
        need.append("Category certificate")
    return need


TICKET_CATEGORIES = ["Admission", "Academic", "Fees and scholarships", "Hostel and facilities",
                     "Ragging or harassment", "Technical problem with this website", "Other"]
TICKET_STATUSES = ["Open", "In progress", "Resolved", "Closed"]

SCHOLARSHIPS = [
    ("Merit scholarship", "Applicants with outstanding marks in the qualifying examination.",
     "Considered automatically from the marks in your application."),
    ("Sports scholarship", "Students who have represented their school, district or state in a recognised sport.",
     "Bring certificates to counselling."),
    ("Economically weaker section (EWS)", "Students from families that meet the income criteria for EWS.",
     "Bring a valid EWS certificate to counselling."),
    ("Girl-child scholarship", "Women applicants to technology programmes.",
     "No separate form. Eligibility is read from your application."),
]

# ---------------------------------------------------------------------------
# About page content - edit freely. Plain text only.
# ---------------------------------------------------------------------------
PURPOSE = [
    "MIUTM exists to bring serious technology and management education to Ayodhya. Many capable "
    "students in this region travel far to study computing or business, and some never get the "
    "chance. We want a student here to find a rigorous, practical degree close to home, with the "
    "same tools and expectations as any good university in India.",
    "We also know that students arrive from different starting points. Some are finishing class 12, "
    "some already hold a degree, and some simply want a six-month skill. So every programme has "
    "clear entry rules, a published merit process and an online tracker, and nobody has to guess "
    "where they stand.",
]

MISSION = ("To educate students in computing, engineering and management through practice: small "
           "classes, open labs and assessed projects, so that every graduate can build, analyse "
           "and lead with confidence.")

VISION = ("A university from Ayodhya that is known across India for graduates who build useful "
          "technology and run organisations responsibly.")

GOALS = [
    ("Teach the fundamentals properly",
     "Programming, mathematics, data, systems, accounting and communication come first. Specialisation "
     "comes after the base is solid."),
    ("Make every programme project-based",
     "Each semester ends with something built and shown to faculty. We assess working results, not "
     "only exam answers."),
    ("Keep the doors open",
     "Entry points after class 12, after a degree, or as a short course. Eligibility, merit and "
     "scholarships are published, and every application can be tracked online."),
    ("Connect students to real work",
     "Internships, industry talks and live problems from local businesses, schools and public offices."),
    ("Build with responsibility",
     "Privacy, security and ethics are part of every computing course, and honesty is part of every "
     "management one."),
    ("Do research that serves the region",
     "Applied projects in education, public services, small business and agriculture, with students "
     "working alongside faculty."),
]

VALUES = [
    ("Learn by building", "Labs, studios and live projects come before long lectures."),
    ("Fair and transparent", "Published eligibility, a merit list and a status tracker. No hidden steps."),
    ("Open to every stream", "Programmes start at different levels so more people can find a way in."),
    ("Responsible technology", "We teach what is possible and also what is right: security, privacy, consent."),
    ("Respect for people", "An inclusive campus, scholarships and mentoring so ability, not background, decides outcomes."),
    ("Always improving", "Students give feedback every semester, and we publish what we change because of it."),
]

LEARNING_MODEL = [
    ("Foundations", "Core subjects in the first year give everyone the same strong base."),
    ("Studio and lab", "Weekly hands-on sessions where concepts are tried, broken and fixed."),
    ("Semester project", "Every semester closes with a project presented to faculty and peers."),
    ("Real-world finish", "A final internship or capstone with an outside organisation."),
]

SCHOOL_BLURBS = {
    "School of Computing Sciences": "Software, databases, the web and the cloud. Home of the BCA and MCA, and the Python and Full Stack certificates.",
    "School of Management Studies": "Business, finance, marketing and people management, with analytics built into the BBA and MBA.",
    "School of Engineering & Applied Technology": "Computer science with engineering depth: algorithms, systems, networks and how software meets hardware.",
    "School of Artificial Intelligence": "Machine learning, deep learning and language models, taught in Python from first principles to deployment.",
    "School of Cyber Security": "Defence, ethical hacking, forensics and incident response, practised in a lab built for safe experiments.",
}

FACILITIES = [
    ("Central digital library", "img/library.webp", "Quiet reading halls, group study rooms and online journal access."),
    ("Advanced computer lab", "img/lab.webp", "Workstations for programming, data and security practicals, open long hours."),
    ("Student hostel", "img/hostel.webp", "Furnished rooms, a study room and a recreation area on campus."),
    ("Smart auditorium", "img/auditorium.webp", "Seminars, guest lectures, project demonstrations and cultural events."),
    ("Sports ground", "img/sports.webp", "A field and courts for college teams and everyday fitness."),
    ("Cafeteria", "img/cafeteria.webp", "A shared space for meals, group work and conversation."),
]

RESEARCH_AREAS = [
    ("Applied AI and data", "Models and dashboards that help schools, clinics and small businesses decide better."),
    ("Cyber security and privacy", "Testing and hardening real systems, and teaching safe practice."),
    ("Software and cloud engineering", "Reliable, maintainable software and the infrastructure that runs it."),
    ("Digital management and enterprise", "How technology changes the way small and mid-sized organisations work."),
]

SUPPORT = [
    ("Mentoring", "Every first-year student has a faculty mentor for academic and personal guidance."),
    ("Career and placement cell", "CV clinics, mock interviews, internship matching and employer visits."),
    ("Scholarships", "Merit, sports, economically weaker section and girl-child scholarships."),
    ("Bridge classes", "Extra mathematics and English classes for students who want a stronger start."),
    ("Wellbeing", "A counselling desk, a hostel warden and a grievance process that gets answered."),
]

JOURNEY = [
    ("2026", "MIUTM is founded in Ayodhya with five schools and ten programmes.", "done"),
    ("Oct 2026", "The online admission portal opens for the 2027\u201328 session.", "done"),
    ("Aug 2027", "First classes begin for the 2027\u201328 batch.", "next"),
    ("Planned", "A research centre and a student incubation space.", "later"),
]

FOUNDER_MESSAGE = {
    "text": ("We started MIUTM with a simple belief: a student should leave with something built, not "
             "just something memorised. Our job is to give you strong foundations, good tools and the "
             "nerve to start. Come and see our labs, ask hard questions, and decide for yourself."),
    "name": "Nitin Kumar",
    "role": "Founder and Director, IT",
    "photo": "img/team/nitin.webp",
}


# ---------------------------------------------------------------------------
# About page: university profile (edit freely, plain text only)
# ---------------------------------------------------------------------------
ABOUT_LEDE = ("Maurya International University of Technology & Management (MIUTM) is a university in Ayodhya, "
              "Uttar Pradesh. It teaches computing, artificial intelligence, cyber security, engineering and "
              "management through certificates, diplomas and degrees, with practical work in every programme and "
              "an admission process that is clear and fair.")

WHY_AYODHYA = ("Ayodhya is an ancient city on the banks of the Sarayu river in eastern Uttar Pradesh. As the city and "
               "its region grow, more young people want modern technology and management education without moving "
               "hundreds of kilometres from home. MIUTM is built to meet that need locally.")

LEVEL_INFO = {
    "Certificate": "Short, skill-focused courses of about six months for school leavers, graduates and working people who want one practical skill.",
    "Diploma": "One-year programmes that go deeper into a single field and lead directly to jobs or further study.",
    "Undergraduate": "Three- and four-year degrees that build a full foundation, with projects in every semester.",
    "Postgraduate": "Two-year degrees for graduates who want advanced skills in software or management.",
}

ACADEMIC_FRAMEWORK = [
    ("Foundations before specialisation",
     "Programming, mathematics, data, accounting and communication come first, so later choices rest on solid ground."),
    ("A project in every semester",
     "Each semester closes with a project that is shown to faculty and assessed on what works."),
    ("Marks from more than one exam",
     "Coursework, lab work and projects count alongside written examinations, so one exam day does not decide a semester."),
    ("Electives across schools",
     "Students can take electives in other schools, for example security for a software student or analytics for a business student."),
    ("Entry at the right level",
     "Applicants can join after class 12, after a degree, or for a short course, with the eligibility for each published in advance."),
]

ADMISSION_PRINCIPLES = [
    ("Published rules", "Eligibility, minimum marks and fees for every programme are on its page before you apply."),
    ("Merit decides", "Applicants are ranked by marks, then by date of application. Staff can see the ranking behind every decision."),
    ("Online and trackable", "Apply online, upload documents, and follow the status of your application at any time."),
    ("Documents checked in person", "Originals are verified at counselling before a seat is confirmed."),
    ("Scholarships from the same application", "Merit, sports, economically weaker section and girl-child scholarships are considered without a separate form."),
    ("A fair waiting list", "When seats are full, further applicants are waitlisted in merit order and promoted if a seat opens."),
]

GOVERNANCE = ("The university is led by its Founder and Director, with coordinators for technology, research and "
              "administration. Each school is headed by a senior faculty member, and the offices below handle "
              "admission, examinations, fees, placement and support.")
