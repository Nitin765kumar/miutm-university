"""seed_data.py - starter content for a new database (programmes, notices, FAQs, events, faculty)."""

# code, slug, name, level, school, duration, eligibility, min_percent, accepts, audience,
# fee, fee_period, seats, summary, topics
COURSES = [
    ("BCA", "bca", "Bachelor of Computer Applications", "Undergraduate",
     "School of Computing Sciences", "3 years",
     "12th with Mathematics or Computer Science, at least 50% marks.", 50,
     "12th (Intermediate)", "s12m", 95000, "per year", 120,
     "Programming, databases, web development and software projects, with AI and "
     "cybersecurity fundamentals in the later semesters.",
     "Programming,Database systems,Web development,Cloud computing,Artificial intelligence,"
     "Cybersecurity basics,Major project"),
    ("BBA", "bba", "Bachelor of Business Administration", "Undergraduate",
     "School of Management Studies", "3 years",
     "12th in any stream, at least 50% marks.", 50,
     "12th (Intermediate)", "s12m s12o", 105000, "per year", 120,
     "Business fundamentals, finance, marketing and communication for students who want to "
     "lead teams or start a venture.",
     "Management principles,Financial accounting,Marketing,Business communication,"
     "Entrepreneurship,Corporate strategy"),
    ("BTECH-CSE", "btech-cse", "Bachelor of Technology (Computer Science & Engineering)",
     "Undergraduate", "School of Engineering & Applied Technology", "4 years",
     "12th with Physics, Chemistry and Mathematics, at least 60% marks.", 60,
     "12th (Intermediate)", "s12m", 185000, "per year", 180,
     "A four-year engineering degree in computer science covering systems, software, "
     "AI and security.",
     "Data structures and algorithms,Machine learning,Cybersecurity,Full-stack development,"
     "Cloud computing,Data science,Distributed systems,Computer architecture"),
    ("BAI", "bai", "Bachelor of Artificial Intelligence", "Undergraduate",
     "School of Artificial Intelligence", "4 years",
     "12th with Physics, Chemistry and Mathematics, or with Computer Science, "
     "at least 55% marks.", 55,
     "12th (Intermediate)", "s12m", 165000, "per year", 120,
     "Machine learning from first principles to deployment, with Python as the working language.",
     "Machine learning,Deep learning,Generative AI,Natural language processing,Computer vision,"
     "Robotics,Python programming,Data science,Model deployment"),
    ("MCA", "mca", "Master of Computer Applications", "Postgraduate",
     "School of Computing Sciences", "2 years",
     "Bachelor's degree in computer applications or computer science, at least 55% marks.", 55,
     "Bachelor's degree,Master's degree", "gcs", 110000, "per year", 60,
     "Advanced software engineering for graduates, with enterprise systems, cloud and AI.",
     "Enterprise software design,Artificial intelligence,Cybersecurity,Full-stack development,"
     "Big data analytics,DevOps,Cloud-native applications"),
    ("MBA", "mba", "Master of Business Administration", "Postgraduate",
     "School of Management Studies", "2 years",
     "Bachelor's degree in any discipline, at least 50% marks, and a valid national "
     "entrance test score.", 50,
     "Bachelor's degree,Master's degree", "gcs gany", 145000, "per year", 90,
     "Management for graduates from any discipline, with finance, marketing, people and "
     "analytics tracks.",
     "Operations,Human resources,Marketing analytics,Corporate governance,Finance,Strategy"),
    ("DCSEH", "dcseh", "Diploma in Cyber Security & Ethical Hacking", "Diploma",
     "School of Cyber Security", "1 year",
     "12th or equivalent from any recognised board.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "s12m s12o", 85000, "total", 60,
     "Hands-on security training: finding weaknesses, defending networks and responding to incidents.",
     "Network security,Ethical hacking,Penetration testing,Digital forensics,Malware analysis,"
     "Kali Linux,SIEM tools,Incident response,Cyber law"),
    ("CSEH-ADV", "cseh-adv", "Cyber Security & Ethical Hacking (Advanced)", "Diploma",
     "School of Cyber Security", "1 year",
     "Graduation or diploma in computer science or IT, or equivalent knowledge.", 0,
     "Diploma,Bachelor's degree,Master's degree", "gcs", 95000, "total", 60,
     "Specialist training for people who already work with computers and want a security career.",
     "Red and blue teaming,Penetration testing,Cloud security,Threat intelligence,"
     "Security operations centre,Digital forensics,Vulnerability assessment"),
    ("APP", "app", "Advanced Python Programming", "Certificate",
     "School of Computing Sciences", "6 months",
     "Basic knowledge of programming or Python fundamentals.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "short", 35000, "total", 80,
     "A project-based certificate that takes you from solid Python basics to building and "
     "deploying real applications.",
     "Object-oriented programming,Automation,APIs,Django,Flask,Data analysis,Web scraping,"
     "Multithreading"),
    ("FSD", "fsd", "Full Stack Development", "Certificate",
     "School of Computing Sciences", "6 months",
     "Basic understanding of HTML, CSS and programming fundamentals.", 0,
     "12th (Intermediate),Diploma,Bachelor's degree,Master's degree", "short", 45000, "total", 100,
     "Build complete web applications, from the interface to the database to deployment.",
     "HTML5 and CSS3,JavaScript,React,Node.js and Express,REST APIs,MongoDB,SQL databases,"
     "Git,Docker,Deployment"),
]

NOTICES = [
    ("Applications for the 2027\u201328 session are open", "Admissions",
     "Apply online until 30 April 2027. You get an application number immediately and can "
     "follow your progress with the tracker.", "2026-10-01"),
    ("Scholarship categories for 2027\u201328", "Scholarships",
     "Merit, sports, economically weaker section and girl-child scholarships are available. "
     "Amounts and eligibility are confirmed by the admissions office.", "2026-10-06"),
    ("Campus visits: book a slot", "Campus",
     "Prospective students and parents can visit the campus on weekdays. Contact the "
     "admissions office to reserve a time.", "2026-10-09"),
]

FACULTY = [
    ("Dr. Arindam Chaudhury", "Senior Professor and Dean", "School of Engineering & Applied Technology",
     "Distributed systems and neural networks"),
    ("Prof. Sarah Mathew", "Head of Department", "School of Management Studies",
     "Strategic marketing and corporate valuation"),
    ("Dr. Rajeev N. Verma", "Director of Research", "School of Computing Sciences",
     "Cryptographic protocols and blockchain architecture"),
    ("Dr. Elena Rostova", "Associate Professor", "School of Engineering & Applied Technology",
     "Optimisation and quantum physics models"),
]


FAQS = [
    ("Can I apply to more than one programme?",
     "Yes. Submit a separate application for each programme. You cannot have two open applications for "
     "the same programme with the same email.", 1),
    ("How will I know my application was received?",
     "You get an application number on screen as soon as you submit, and an email if the site has email "
     "switched on. Save the number. Create a student account to see all your applications in one place.", 2),
    ("How do I check my status?",
     "Log in to your student dashboard, or use the tracker with your application number and date of birth. "
     "Pending means received, Under Review means the office is checking your details, Approved means you "
     "can go to counselling, Waitlisted means you are in line for a seat, and Rejected means the "
     "application was not accepted.", 3),
    ("I made a mistake in my application. What now?",
     "While your status is Pending you can edit the application from your student dashboard. After that, "
     "contact the admissions office with your application number.", 4),
    ("Can I withdraw my application?",
     "Yes. Open the application in your student dashboard and choose Withdraw. The status changes to "
     "Cancelled and your seat is released.", 5),
    ("Is there an entrance test?",
     "Most programmes admit on merit. The MBA also needs a valid national entrance test score.", 6),
    ("How do I pay the fee?",
     "Fee payment instructions are given at counselling, after your application is approved. Do not pay "
     "anyone before that.", 7),
]

EVENTS = [
    ("Campus open day", "Meet faculty, see the labs and ask the admissions team your questions.",
     "MIUTM Campus, Ayodhya", "2026-11-07", None),
    ("Online admission help session", "A live walkthrough of the application form and eligibility rules.",
     "Online", "2027-01-16", None),
    ("Orientation week", "A week of introductions, lab tours and workshops for the new batch.",
     "MIUTM Campus, Ayodhya", "2027-08-02", "2027-08-06"),
]
