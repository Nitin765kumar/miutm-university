"""pdfdocs.py - every downloadable PDF: syllabus, prospectus, fee structure, receipts and letters (reportlab)."""
import io
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY, GOLD, GRID, PAPER = colors.HexColor("#13294B"), colors.HexColor("#E0B03A"), colors.HexColor("#C9D1E0"), colors.HexColor("#F3F5F9")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, spaceAfter=4)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10.5, textColor=colors.HexColor("#526078"))
H1 = ParagraphStyle("h1", parent=BODY, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=NAVY, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=5)
H3 = ParagraphStyle("h3", parent=BODY, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=NAVY, spaceBefore=4, spaceAfter=2)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.8, leading=11, spaceAfter=0)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")


def clean(x):
    """Text safe for the built-in PDF fonts (no rupee sign there) and for the Paragraph mini-markup."""
    s = "" if x is None else str(x)
    s = s.replace("\u20b9", "Rs. ")
    return escape(s).encode("cp1252", "replace").decode("cp1252")


def plain(x):
    """Text for drawing straight onto the page (no markup escaping)."""
    return ("" if x is None else str(x)).replace("\u20b9", "Rs. ").encode("cp1252", "replace").decode("cp1252")


def P(text, style=BODY):
    return Paragraph(clean(text), style)


def ist(ts):
    if not ts:
        return ""
    d = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=5, minutes=30)
    return f"{d.day} {d:%b %Y}, {d.strftime('%I:%M %p').lstrip('0').lower()}"


def dmy(value):
    d = value if hasattr(value, "day") else datetime.strptime(str(value)[:10], "%Y-%m-%d")
    return f"{d.day} {d:%b %Y}"


def money(n):
    n = int(n)
    s = str(abs(n))
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return "Rs. " + s


def table(rows, widths, header=True, zebra=True):
    data = [[c if not isinstance(c, str) else P(c, CELLB if (header and i == 0) else CELL) for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), PAPER), ("LINEBELOW", (0, 0), (-1, 0), 1, NAVY)]
    t.setStyle(TableStyle(style))
    return t


def facts(pairs, widths=(45 * mm, 125 * mm)):
    t = Table([[P(k, CELLB), P(v, CELL)] for k, v in pairs], colWidths=widths)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def build(title, story, site, demo=True, session=None):
    buf = io.BytesIO()

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(18 * mm, A4[1] - 9 * mm, plain(site["name"]))
        canvas.setFillColor(GOLD)
        canvas.rect(0, A4[1] - 15 * mm, A4[0], 1 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#526078"))
        canvas.setFont("Helvetica", 7.5)
        note = ("Demonstration institution. Names, figures and fees are sample data.  " if demo else "")
        canvas.drawString(18 * mm, 10 * mm, plain(note + (f"Session {session}" if session else "")))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=24 * mm,
                            bottomMargin=18 * mm, title=clean(title), author=clean(site["name"]))
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()


# ---------------------------------------------------------------------------
def syllabus_pdf(site, session, course, semesters, total_credits, demo=True):
    story = [P(course["name"], H1), P("Programme syllabus", H3), Spacer(1, 3 * mm)]
    story.append(facts([("Programme code", course["code"]), ("Level", course["level"]), ("School", course["school"]),
                        ("Duration", course["duration"]), ("Eligibility", course["eligibility"]),
                        ("Academic session", session), ("Total credits", str(total_credits))]))
    for sem, subjects in semesters.items():
        credits = sum(s["credits"] for s in subjects)
        label = f"Semester {sem}" if len(semesters) > 1 else "Modules"
        story.append(KeepTogether([P(f"{label} ({credits} credits)", H2)]))
        rows = [["Code", "Subject", "Credits", "Type"]] + [[s["code"], s["name"], str(s["credits"]), s["kind"]] for s in subjects]
        story.append(table(rows, [24 * mm, 100 * mm, 20 * mm, 26 * mm]))
        story.append(Spacer(1, 2 * mm))
        for s in subjects:
            units = "; ".join(f"{u['unit_no']}. {u['title']}" for u in s["units"])
            story.append(KeepTogether([P(f"{s['code']}  {s['name']}", H3), P("Units: " + units, SMALL)]))
    story += [Spacer(1, 4 * mm), HRFlowable(width="100%", color=GRID), P(f"Total credits: {total_credits}", H3)]
    return build(f"{course['name']} syllabus", story, site, demo, session)


def prospectus_pdf(site, cycle, courses, schools, app_fee, scholarships, demo=True):
    story = [Spacer(1, 25 * mm), P(site["name"], H1), P("Prospectus " + cycle["session"], ParagraphStyle("sub", parent=H2, fontSize=16, leading=20)),
             Spacer(1, 6 * mm), P(site["tagline"], BODY), Spacer(1, 4 * mm),
             facts([("Location", ", ".join(site["address"])), ("Phone", site["phone"]), ("Email", site["general_email"]),
                    ("Office hours", site["hours"])]), PageBreak()]
    story += [P("About the university", H2),
              P("MIUTM teaches computing, artificial intelligence, cyber security, engineering and management through certificates, "
                "diplomas and degrees, with practical work in every programme and an admission process that is clear and fair.")]
    story.append(P("Schools and programmes", H2))
    for school, items in schools.items():
        story.append(P(school, H3))
        rows = [["Programme", "Level", "Duration", "Seats", "Fee"]] + [
            [c["name"], c["level"], c["duration"], str(c["seats"]), f"{money(c['fee'])} {c['fee_period']}"] for c in items]
        story += [table(rows, [66 * mm, 26 * mm, 22 * mm, 14 * mm, 42 * mm]), Spacer(1, 2 * mm)]
    story.append(P("How to apply", H2))
    for i, step in enumerate(["Create a student account on the website.", "Fill in the five-step application and upload your documents.",
                              f"Pay the application fee ({money(app_fee)}) to submit." if app_fee else "Submit your application.",
                              "Track your status on your dashboard. Selected applicants pay the admission fee.",
                              "Attend counselling with your original documents to confirm your seat."], 1):
        story.append(P(f"{i}. {step}"))
    story.append(P("Key dates", H2))
    story.append(table([["Step", "Date"]] + [[m["label"], dmy(m["date"])] for m in cycle["milestones"]], [110 * mm, 60 * mm]))
    story.append(P("Scholarships", H2))
    for name, who, how in scholarships:
        story.append(P(f"<b>{clean(name)}.</b> {clean(who)} {clean(how)}"))
    return build("Prospectus", story, site, demo, cycle["session"])


def fee_structure_pdf(site, session, courses, app_fee, demo=True):
    story = [P("Fee structure", H1), P(f"Academic session {session}", H3), Spacer(1, 3 * mm)]
    rows = [["Programme", "Duration", "Programme fee", "Admission fee"]] + [
        [f"{c['name']} ({c['code']})", c["duration"], f"{money(c['fee'])} {c['fee_period']}", money(c["admission_fee"]) if c["admission_fee"] else "None"]
        for c in courses]
    story += [table(rows, [72 * mm, 24 * mm, 42 * mm, 32 * mm]), Spacer(1, 4 * mm),
              P(f"Application fee: {money(app_fee) if app_fee else 'None'}, paid once for each application.", BODY),
              P("The admission fee is paid after selection and secures the seat. Fees are shown in rupees. "
                "Refunds follow the refund and cancellation policy published on the website.", SMALL)]
    return build("Fee structure", story, site, demo, session)


def application_receipt_pdf(site, a, payment=None, demo=True):
    story = [P("Application receipt", H1), Spacer(1, 3 * mm)]
    rows = [("Application number", a["application_no"]), ("Applicant", a["full_name"]), ("Programme", a["course_name"]),
            ("Session", a["session"] or ""), ("Submitted", ist(a["submitted_at"] or a["created_at"])), ("Status", a["status"]),
            ("Email", a["email"]), ("Mobile", a["phone"])]
    if payment is not None:
        rows += [("Application fee", f"{money(payment['amount'])} ({payment['status']})"), ("Transaction ID", payment["transaction_id"] or "")]
    story += [facts(rows), Spacer(1, 6 * mm),
              P("Keep this receipt. You can follow your application on your student dashboard.", SMALL)]
    return build("Application receipt", story, site, demo, a["session"])


def payment_receipt_pdf(site, a, p, demo=True):
    story = [P("Fee payment receipt", H1), Spacer(1, 3 * mm),
             facts([("Receipt for", p["purpose"]), ("Student", a["full_name"]), ("Application number", a["application_no"]),
                    ("Programme", a["course_name"]), ("Order ID", p["order_id"]), ("Transaction ID", p["transaction_id"] or ""),
                    ("Payment ID", p["payment_ref"] or ""), ("Amount", money(p["amount"])), ("Payment method", p["method"] or ""),
                    ("Date and time", ist(p["paid_at"])), ("Payment status", p["status"])]),
             Spacer(1, 6 * mm)]
    if p["status"] == "Refunded":
        story.append(P(f"This payment was refunded on {ist(p['refunded_at'])}. {p['refund_reason'] or ''}", BODY))
    story.append(P("This is a computer-generated receipt and needs no signature. " + ("This is a demonstration payment: no money was charged." if demo else ""), SMALL))
    return build("Payment receipt", story, site, demo, a["session"])


def admission_letter_pdf(site, a, course, docs_needed, counselling, classes, demo=True):
    story = [P("Provisional admission letter", H1), P(f"Reference: {a['application_no']}", SMALL), Spacer(1, 4 * mm),
             P(f"Dear {a['full_name']},"),
             P(f"We are pleased to tell you that your admission to <b>{clean(a['course_name'])}</b> for the {clean(a['session'] or '')} session "
               "has been approved.")]
    rows = [("Programme", a["course_name"]), ("Duration", course["duration"] if course else ""),
            ("Fee", f"{money(course['fee'])} {course['fee_period']}" if course else "")]
    if counselling:
        rows.append(("Counselling from", dmy(counselling)))
    if classes:
        rows.append(("Classes begin", dmy(classes)))
    story += [facts(rows), Spacer(1, 3 * mm), P("Please bring these original documents to counselling:", BODY)]
    story += [P("- " + d) for d in docs_needed + ["This letter"]]
    story += [Spacer(1, 4 * mm), P("This offer depends on verification of your documents. We look forward to welcoming you."),
              Spacer(1, 12 * mm), P("Registrar", H3), P(site["name"], SMALL)]
    return build("Admission letter", story, site, demo, a["session"])


def confirmation_letter_pdf(site, a, course, classes, demo=True):
    story = [P("Admission confirmation letter", H1), P(f"Reference: {a['application_no']}", SMALL), Spacer(1, 4 * mm),
             P(f"Dear {a['full_name']},"),
             P(f"This letter confirms your admission to <b>{clean(a['course_name'])}</b> at {clean(site['name'])} for the "
               f"{clean(a['session'] or '')} session. Your seat is secured."),
             facts([("Student", a["full_name"]), ("Programme", a["course_name"]), ("Application number", a["application_no"]),
                    ("Classes begin", dmy(classes) if classes else "To be announced")]), Spacer(1, 4 * mm),
             P("Welcome to MIUTM. Watch your notifications for orientation details."), Spacer(1, 12 * mm),
             P("Registrar", H3), P(site["name"], SMALL)]
    return build("Admission confirmation", story, site, demo, a["session"])
