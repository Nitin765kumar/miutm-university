"""
syllabus_data.py - semester-wise syllabus for every programme, and the programme descriptions.

One subject per line:  code | name | credits | T (theory) or P (practical) | unit; unit; unit
A line starting with # starts a semester. Short courses use a single block of modules.
The content is illustrative for this demonstration institution. It is loaded into the database the first time
the site starts; after that, edit it in the database.
"""

_RAW = {}

_RAW["BCA"] = """
# 1
BCA101 | Programming Fundamentals | 4 | T | Introduction to Programming; Variables and Data Types; Operators; Conditional Statements; Loops; Functions
BCA102 | Computer Fundamentals | 4 | T | History and Generations of Computers; Hardware Components; Memory and Storage; Operating System Basics; Number Systems
BCA103 | Mathematics-I | 4 | T | Sets and Relations; Functions; Matrices; Determinants; Basic Probability
BCA104 | Programming Lab | 2 | P | Basic C Programs; Control Structure Programs; Function Programs; Array Programs
BCA105 | Communication Skills | 3 | T | Grammar and Usage; Reading Comprehension; Professional Writing; Presentation Skills
# 2
BCA201 | Data Structures | 4 | T | Arrays and Linked Lists; Stacks; Queues; Trees; Graphs; Sorting and Searching
BCA202 | Digital Logic and Computer Architecture | 4 | T | Logic Gates; Combinational Circuits; Sequential Circuits; CPU Organisation; Memory Hierarchy
BCA203 | Mathematics-II (Statistics) | 4 | T | Descriptive Statistics; Probability Distributions; Sampling; Hypothesis Testing; Correlation and Regression
BCA204 | Data Structures Lab | 2 | P | Linked List Programs; Stack and Queue Programs; Tree Programs; Sorting Programs
BCA205 | Environmental Studies | 3 | T | Ecosystems; Natural Resources; Pollution and Control; Sustainable Development
# 3
BCA301 | Object-Oriented Programming | 4 | T | Classes and Objects; Inheritance; Polymorphism; Exception Handling; File Handling
BCA302 | Database Management Systems | 4 | T | Database Concepts; ER Modelling; Relational Model and SQL; Normalisation; Transactions
BCA303 | Operating Systems | 4 | T | Process Management; CPU Scheduling; Memory Management; File Systems; Deadlocks
BCA304 | Web Technologies | 3 | T | HTML and CSS; JavaScript Basics; Responsive Design; Forms and Validation
BCA305 | Object-Oriented Programming Lab | 2 | P | Class Programs; Inheritance Programs; Exception Programs
BCA306 | DBMS Lab | 2 | P | DDL and DML Commands; Joins and Subqueries; Views and Indexes; PL/SQL Basics
# 4
BCA401 | Software Engineering | 4 | T | Software Process Models; Requirements Analysis; Design Principles; Testing; Maintenance and Project Management
BCA402 | Computer Networks | 4 | T | Network Models; Physical and Data Link Layers; Network Layer and IP; Transport Layer; Application Protocols
BCA403 | Design and Analysis of Algorithms | 4 | T | Algorithm Analysis; Divide and Conquer; Greedy Methods; Dynamic Programming; Graph Algorithms
BCA404 | Python Programming | 3 | T | Python Basics; Data Structures in Python; Functions and Modules; File and Exception Handling; Libraries
BCA405 | Python Lab | 2 | P | Python Basics Programs; Data Structure Programs; Library Programs
BCA406 | Mini Project | 2 | P | Problem Definition; Design; Implementation; Demonstration
# 5
BCA501 | Artificial Intelligence Fundamentals | 4 | T | Introduction to AI; Search Techniques; Knowledge Representation; Machine Learning Overview; AI Applications and Ethics
BCA502 | Cloud Computing | 4 | T | Cloud Concepts; Virtualisation; Service Models; Deployment and Scaling; Cloud Security
BCA503 | Cyber Security Basics | 3 | T | Security Concepts; Cryptography Basics; Network Security; Web Security; Cyber Law
BCA504 | Elective I: Mobile Application Development | 3 | T | Mobile Platforms; User Interface Design; Data Storage; Networking and APIs; Publishing Apps
BCA505 | Web Development Lab | 2 | P | Front-End Pages; Server-Side Scripting; Database Connectivity
BCA506 | Minor Project | 3 | P | Proposal; Development; Testing; Report and Viva
# 6
BCA601 | Machine Learning Basics | 4 | T | Supervised Learning; Unsupervised Learning; Model Evaluation; Feature Engineering; Introduction to Neural Networks
BCA602 | Information Systems and E-Commerce | 3 | T | Information Systems; E-Commerce Models; Digital Payments; Security in E-Commerce
BCA603 | Professional Ethics and Entrepreneurship | 3 | T | Professional Ethics; Intellectual Property; Startup Basics; Business Planning
BCA604 | Elective II: Data Analytics | 3 | T | Data Collection; Cleaning and Preparation; Visualisation; Reporting and Dashboards
BCA605 | Major Project | 8 | P | Requirement Study; System Design; Implementation; Testing and Deployment; Final Report and Viva
"""

_RAW["BBA"] = """
# 1
BBA101 | Principles of Management | 4 | T | Nature of Management; Planning; Organising; Directing; Controlling
BBA102 | Business Economics | 4 | T | Demand and Supply; Consumer Behaviour; Production and Cost; Market Structures; National Income
BBA103 | Financial Accounting | 4 | T | Accounting Principles; Journal and Ledger; Trial Balance; Final Accounts; Depreciation
BBA104 | Business Communication | 3 | T | Communication Process; Business Letters; Reports and Proposals; Presentations; Email Etiquette
BBA105 | Business Mathematics | 3 | T | Ratio and Proportion; Percentages and Interest; Equations; Matrices; Basic Statistics
# 2
BBA201 | Organisational Behaviour | 4 | T | Individual Behaviour; Motivation; Group Dynamics; Leadership; Organisational Culture
BBA202 | Cost Accounting | 4 | T | Cost Concepts; Material Costing; Labour Costing; Overheads; Job and Process Costing
BBA203 | Business Statistics | 4 | T | Data Presentation; Measures of Central Tendency; Dispersion; Correlation; Index Numbers
BBA204 | Marketing Management | 4 | T | Marketing Concepts; Segmentation and Targeting; Product and Pricing; Promotion; Distribution
BBA205 | Computer Applications in Business | 2 | P | Spreadsheet Skills; Word Processing; Presentation Tools; Basic Databases
# 3
BBA301 | Human Resource Management | 4 | T | HR Planning; Recruitment and Selection; Training and Development; Performance Appraisal; Compensation
BBA302 | Financial Management | 4 | T | Financial Goals; Time Value of Money; Capital Budgeting; Cost of Capital; Working Capital
BBA303 | Business Law | 3 | T | Contract Law; Sale of Goods; Companies Act Basics; Consumer Protection
BBA304 | Operations Management | 3 | T | Production Systems; Inventory Control; Quality Management; Supply Chain Basics
BBA305 | Digital Marketing | 3 | T | Digital Channels; Search and Social Media; Content Marketing; Analytics and Measurement
# 4
BBA401 | Management Accounting | 4 | T | Budgeting; Standard Costing; Variance Analysis; Marginal Costing; Decision Making
BBA402 | Research Methodology | 3 | T | Research Design; Sampling; Data Collection; Analysis and Reporting
BBA403 | Consumer Behaviour | 3 | T | Consumer Decision Process; Perception and Learning; Attitudes; Culture and Influence
BBA404 | Entrepreneurship Development | 3 | T | Entrepreneurial Mindset; Opportunity Identification; Business Plan; Funding and Support
BBA405 | Business Analytics Lab | 2 | P | Data Cleaning; Pivot Tables; Charts and Dashboards
BBA406 | Summer Internship | 2 | P | Placement; Work Log; Internship Report; Viva
# 5
BBA501 | Strategic Management | 4 | T | Strategy Concepts; Environmental Analysis; Strategy Formulation; Implementation; Evaluation
BBA502 | Banking and Insurance | 3 | T | Banking System; Banking Products; Insurance Principles; Risk Management
BBA503 | International Business | 3 | T | Global Trade; Trade Policy; Foreign Exchange; Global Marketing
BBA504 | Elective I: Specialisation (Finance, Marketing or HR) | 3 | T | Foundations of the Specialisation; Tools and Techniques; Case Studies; Current Practices
BBA505 | Corporate Social Responsibility | 2 | T | CSR Concepts; Legal Framework; Sustainability; CSR Case Studies
BBA506 | Minor Project | 3 | P | Topic Selection; Data Collection; Analysis; Report and Viva
# 6
BBA601 | Corporate Governance and Ethics | 3 | T | Governance Principles; Board Structure; Business Ethics; Whistle-blowing and Compliance
BBA602 | Project Management | 3 | T | Project Life Cycle; Scheduling; Cost and Risk; Monitoring and Closure
BBA603 | Elective II: Specialisation | 3 | T | Advanced Concepts; Applications; Case Studies; Trends
BBA604 | Elective III: Specialisation | 3 | T | Advanced Concepts; Applications; Case Studies; Trends
BBA605 | Major Project and Viva | 8 | P | Problem Statement; Fieldwork; Analysis and Findings; Final Report and Viva
"""

_RAW["BTECH-CSE"] = """
# 1
BTC101 | Engineering Mathematics-I | 4 | T | Differential Calculus; Integral Calculus; Sequences and Series; Multivariable Calculus; Vector Calculus
BTC102 | Engineering Physics | 4 | T | Wave Optics; Quantum Mechanics Basics; Lasers and Fibre Optics; Semiconductors; Electromagnetism
BTC103 | Programming for Problem Solving | 4 | T | Problem Solving and Algorithms; Basics of C; Control Statements; Arrays and Strings; Functions and Pointers
BTC104 | Basic Electrical Engineering | 3 | T | DC Circuits; AC Circuits; Transformers; Electrical Machines; Safety and Measurements
BTC105 | Engineering Graphics | 2 | P | Drawing Basics; Projections; Sections; Computer-Aided Drawing
BTC106 | Programming Lab | 2 | P | C Basics; Control Structures; Arrays and Strings; Functions and Pointers
# 2
BTC201 | Engineering Mathematics-II | 4 | T | Linear Algebra; Eigenvalues and Eigenvectors; Ordinary Differential Equations; Laplace Transforms; Complex Numbers
BTC202 | Engineering Chemistry | 4 | T | Water Treatment; Electrochemistry; Polymers; Fuels; Engineering Materials
BTC203 | Data Structures | 4 | T | Arrays and Linked Lists; Stacks and Queues; Trees; Graphs; Hashing; Sorting
BTC204 | Digital Electronics | 4 | T | Number Systems; Logic Gates; Combinational Logic; Sequential Logic; Memories
BTC205 | Communication Skills | 3 | T | Listening and Speaking; Technical Writing; Group Discussion; Interview Skills
BTC206 | Data Structures Lab | 2 | P | Linked Lists; Stacks and Queues; Trees; Sorting
# 3
BTC301 | Discrete Mathematics | 4 | T | Logic and Proofs; Sets and Relations; Graph Theory; Combinatorics; Algebraic Structures
BTC302 | Object-Oriented Programming | 4 | T | Classes and Objects; Inheritance; Polymorphism; Exceptions; Generics and Collections
BTC303 | Computer Organisation and Architecture | 4 | T | Instruction Set Architecture; Processor Design; Pipelining; Memory Systems; I/O Organisation
BTC304 | Database Management Systems | 4 | T | Relational Model; SQL; Normalisation; Transactions; Indexing and Storage
BTC305 | Operating Systems | 4 | T | Processes and Threads; Scheduling; Memory Management; File Systems; Synchronisation
BTC306 | OOP and DBMS Lab | 2 | P | Object-Oriented Programs; SQL Queries; Mini Application
# 4
BTC401 | Design and Analysis of Algorithms | 4 | T | Complexity Analysis; Divide and Conquer; Greedy Algorithms; Dynamic Programming; NP-Completeness
BTC402 | Theory of Computation | 4 | T | Finite Automata; Regular Languages; Context-Free Grammars; Turing Machines; Decidability
BTC403 | Computer Networks | 4 | T | Network Architecture; Link and Network Layers; Transport Layer; Application Layer; Network Security Basics
BTC404 | Software Engineering | 3 | T | Process Models; Requirements; Design and Architecture; Testing; Agile Practice
BTC405 | Probability and Statistics | 3 | T | Probability; Random Variables; Distributions; Estimation; Hypothesis Testing
BTC406 | Networks and Algorithms Lab | 2 | P | Socket Programming; Network Simulation; Algorithm Implementation
# 5
BTC501 | Compiler Design | 4 | T | Lexical Analysis; Parsing; Semantic Analysis; Code Generation; Optimisation
BTC502 | Machine Learning | 4 | T | Regression; Classification; Clustering; Neural Networks; Model Evaluation
BTC503 | Web and Mobile Application Development | 3 | T | Front-End Frameworks; Back-End Services; REST APIs; Mobile Apps; Deployment
BTC504 | Information Security | 3 | T | Cryptography; Authentication; Network and Web Security; Secure Software; Security Policy
BTC505 | Professional Elective I | 3 | T | Foundations; Techniques; Tools; Case Studies
BTC506 | Machine Learning and Web Lab | 2 | P | ML Experiments; Web Applications; Integration
# 6
BTC601 | Distributed Systems | 4 | T | Architectures; Communication; Consistency and Replication; Fault Tolerance; Distributed Storage
BTC602 | Cloud Computing | 3 | T | Virtualisation; Service Models; Containers and Orchestration; Cloud Security; Cost Management
BTC603 | Data Science and Big Data | 3 | T | Data Pipelines; Statistical Analysis; Big Data Frameworks; Visualisation; Case Studies
BTC604 | Professional Elective II | 3 | T | Foundations; Techniques; Tools; Case Studies
BTC605 | Open Elective I | 3 | T | Foundations; Applications; Case Studies; Current Trends
BTC606 | Minor Project | 3 | P | Proposal; Design and Build; Testing; Report and Viva
# 7
BTC701 | Deep Learning | 4 | T | Neural Network Basics; Convolutional Networks; Sequence Models; Transformers; Training and Deployment
BTC702 | Internet of Things | 3 | T | Sensors and Devices; Embedded Programming; IoT Protocols; Edge and Cloud; IoT Security
BTC703 | Professional Elective III | 3 | T | Foundations; Techniques; Tools; Case Studies
BTC704 | Open Elective II | 3 | T | Foundations; Applications; Case Studies; Current Trends
BTC705 | Industrial Training | 2 | P | Placement; Training Log; Report and Viva
BTC706 | Project Phase I | 4 | P | Literature Survey; Problem Definition; Design; Interim Report
# 8
BTC801 | Professional Elective IV | 3 | T | Foundations; Techniques; Tools; Case Studies
BTC802 | Engineering Ethics and Management | 3 | T | Professional Ethics; Intellectual Property; Project and Finance Management; Entrepreneurship
BTC803 | Seminar | 2 | P | Topic Study; Presentation; Report
BTC804 | Major Project Phase II or Internship | 12 | P | Implementation; Evaluation; Thesis; Final Presentation
"""

_RAW["BAI"] = """
# 1
BAI101 | Programming in Python | 4 | T | Python Basics; Control Flow; Functions and Modules; Data Structures; Files and Exceptions
BAI102 | Mathematics for AI-I (Linear Algebra) | 4 | T | Vectors and Matrices; Systems of Equations; Vector Spaces; Eigenvalues; Singular Value Decomposition
BAI103 | Introduction to Artificial Intelligence | 3 | T | History and Scope of AI; Intelligent Agents; Search; Knowledge and Reasoning; AI in Society
BAI104 | Computer Systems | 3 | T | Digital Logic; Processor Basics; Memory; Operating System Concepts; Networking Basics
BAI105 | Python Lab | 2 | P | Python Programs; Data Structure Programs; File Programs
BAI106 | Communication Skills | 2 | T | Listening and Speaking; Technical Writing; Presentations
# 2
BAI201 | Data Structures and Algorithms | 4 | T | Arrays and Lists; Stacks and Queues; Trees and Graphs; Sorting and Searching; Algorithm Analysis
BAI202 | Mathematics for AI-II (Calculus and Optimisation) | 4 | T | Differentiation; Partial Derivatives and Gradients; Optimisation Methods; Convexity; Numerical Methods
BAI203 | Probability and Statistics | 4 | T | Probability Rules; Random Variables; Common Distributions; Estimation; Hypothesis Testing
BAI204 | Database Systems | 3 | T | Relational Model; SQL; Normalisation; NoSQL Basics; Data Warehousing Basics
BAI205 | Data Structures Lab | 2 | P | Linear Structures; Trees and Graphs; Algorithms
BAI206 | Environmental Studies | 2 | T | Ecosystems; Resources; Pollution; Sustainability
# 3
BAI301 | Machine Learning | 4 | T | Regression; Classification; Decision Trees and Ensembles; Clustering; Model Selection
BAI302 | Data Wrangling and Visualisation | 3 | T | Data Cleaning; Exploratory Analysis; Visualisation Principles; Dashboards
BAI303 | Operating Systems | 3 | T | Processes; Scheduling; Memory Management; File Systems
BAI304 | Object-Oriented Design | 3 | T | Classes and Objects; Design Principles; Design Patterns; Testing
BAI305 | Machine Learning Lab | 2 | P | Regression Experiments; Classification Experiments; Clustering Experiments
BAI306 | Data Lab | 2 | P | Data Cleaning Exercises; Visualisation Projects; Reporting
# 4
BAI401 | Deep Learning | 4 | T | Neural Networks; Backpropagation; Convolutional Networks; Recurrent Networks; Regularisation and Training
BAI402 | Natural Language Processing | 4 | T | Text Processing; Language Models; Embeddings; Sequence Tasks; Applications
BAI403 | Computer Vision | 3 | T | Image Fundamentals; Feature Extraction; Detection and Segmentation; Video Analysis
BAI404 | Software Engineering | 3 | T | Process Models; Requirements; Design; Testing and Delivery
BAI405 | Deep Learning Lab | 2 | P | Neural Network Implementation; CNN Projects; Sequence Model Projects
BAI406 | Mini Project | 2 | P | Problem Definition; Build; Demonstration
# 5
BAI501 | Generative AI and Large Language Models | 4 | T | Transformer Architecture; Pre-training and Fine-tuning; Prompting and Retrieval; Evaluation and Safety; Building Applications
BAI502 | Reinforcement Learning | 3 | T | Markov Decision Processes; Value-Based Methods; Policy Methods; Exploration; Applications
BAI503 | Big Data Technologies | 3 | T | Distributed Storage; Batch Processing; Stream Processing; Data Pipelines
BAI504 | AI Ethics and Governance | 3 | T | Fairness and Bias; Privacy; Transparency; Regulation and Policy
BAI505 | Elective I | 3 | T | Foundations; Techniques; Tools; Case Studies
BAI506 | Generative AI Lab | 2 | P | Prompt Engineering; Retrieval-Based Applications; Fine-Tuning Exercise
# 6
BAI601 | MLOps and Model Deployment | 4 | T | Experiment Tracking; Packaging and Serving; Monitoring; Automation and CI/CD
BAI602 | Robotics and Autonomous Systems | 3 | T | Sensors and Actuators; Perception; Planning and Control; Autonomous Systems
BAI603 | Cloud for AI | 3 | T | Cloud Platforms; GPUs and Training at Scale; Managed AI Services; Cost and Security
BAI604 | Elective II | 3 | T | Foundations; Techniques; Tools; Case Studies
BAI605 | MLOps Lab | 2 | P | Deployment Pipeline; Monitoring Dashboard; Containerisation
BAI606 | Minor Project | 3 | P | Proposal; Development; Evaluation; Report and Viva
# 7
BAI701 | Advanced Deep Learning | 4 | T | Advanced Architectures; Generative Models; Self-Supervised Learning; Efficient Models; Research Readings
BAI702 | AI for Healthcare and Society | 3 | T | Medical Data and Imaging; Clinical Decision Support; Social Impact; Responsible Deployment
BAI703 | Elective III | 3 | T | Foundations; Techniques; Tools; Case Studies
BAI704 | Industrial Training | 2 | P | Placement; Training Log; Report and Viva
BAI705 | Project Phase I | 4 | P | Literature Survey; Problem Definition; Design; Interim Report
# 8
BAI801 | Elective IV | 3 | T | Foundations; Techniques; Tools; Case Studies
BAI802 | Research Methods | 3 | T | Research Design; Literature Review; Experiments and Statistics; Scientific Writing
BAI803 | Seminar | 2 | P | Topic Study; Presentation; Report
BAI804 | Major Project or Internship | 12 | P | Implementation; Evaluation; Thesis; Final Presentation
"""

_RAW["MCA"] = """
# 1
MCA101 | Advanced Data Structures | 4 | T | Advanced Trees; Heaps and Priority Queues; Hashing Techniques; Graph Algorithms; Amortised Analysis
MCA102 | Advanced Database Systems | 4 | T | Query Processing and Optimisation; Transactions and Concurrency; Distributed Databases; NoSQL Systems; Data Warehousing
MCA103 | Computer Networks and Security | 4 | T | Network Protocols; Routing and Switching; Cryptographic Techniques; Network Attacks and Defence; Secure Protocols
MCA104 | Mathematical Foundations of Computing | 3 | T | Logic and Proof; Combinatorics; Graph Theory; Probability and Statistics
MCA105 | Advanced Programming Lab | 2 | P | Data Structure Implementations; Algorithm Programs; Mini Assignments
MCA106 | Database Lab | 2 | P | Advanced SQL; Query Tuning; NoSQL Exercises
# 2
MCA201 | Software Engineering and Design Patterns | 4 | T | Process and Agile Methods; Architecture; Design Patterns; Testing and Quality; Configuration Management
MCA202 | Cloud Computing | 4 | T | Cloud Fundamentals; Virtualisation and Containers; Cloud Services; Scalability and Reliability; Cloud Security
MCA203 | Artificial Intelligence | 4 | T | Intelligent Agents; Search and Planning; Knowledge Representation; Probabilistic Reasoning; Learning Basics
MCA204 | Web Technologies and Frameworks | 3 | T | Front-End Development; Back-End Frameworks; REST and GraphQL APIs; Authentication; Deployment
MCA205 | Elective I | 3 | T | Foundations; Techniques; Tools; Case Studies
MCA206 | Web Development Lab | 2 | P | Full-Stack Application; API Development; Deployment
# 3
MCA301 | Machine Learning | 4 | T | Supervised Learning; Unsupervised Learning; Ensemble Methods; Neural Networks; Model Evaluation and Deployment
MCA302 | Big Data Analytics | 4 | T | Big Data Platforms; Batch and Stream Processing; Data Lakes; Analytics and Visualisation; Case Studies
MCA303 | DevOps and Cloud-Native Applications | 3 | T | Version Control and CI/CD; Containers and Orchestration; Infrastructure as Code; Monitoring and Logging
MCA304 | Elective II | 3 | T | Foundations; Techniques; Tools; Case Studies
MCA305 | Elective III | 3 | T | Foundations; Techniques; Tools; Case Studies
MCA306 | Minor Project | 3 | P | Proposal; Development; Testing; Report and Viva
# 4
MCA401 | Research Methodology and IPR | 3 | T | Research Design; Literature Review; Data Analysis; Intellectual Property; Technical Writing
MCA402 | Cyber Security | 3 | T | Security Principles; Secure Software Development; Threats and Vulnerabilities; Incident Response
MCA403 | Dissertation or Major Project | 12 | P | Problem Formulation; Design and Implementation; Evaluation; Thesis Writing; Viva Voce
MCA404 | Seminar | 2 | P | Topic Study; Presentation; Report
"""

_RAW["MBA"] = """
# 1
MBA101 | Management Principles and Practice | 4 | T | Evolution of Management; Planning and Decision Making; Organising; Leading; Control
MBA102 | Managerial Economics | 4 | T | Demand Analysis; Production and Cost; Market Structures; Pricing Decisions; Macroeconomic Environment
MBA103 | Financial Accounting | 4 | T | Accounting Concepts; Financial Statements; Ratio Analysis; Cash Flow Statements; Corporate Reporting
MBA104 | Organisational Behaviour | 3 | T | Perception and Personality; Motivation; Teams and Groups; Leadership; Change and Culture
MBA105 | Business Statistics | 3 | T | Descriptive Statistics; Probability; Sampling and Estimation; Hypothesis Testing; Regression
MBA106 | Business Communication | 2 | T | Business Writing; Presentations; Negotiation; Cross-Cultural Communication
# 2
MBA201 | Marketing Management | 4 | T | Marketing Strategy; Consumer Insights; Product and Brand; Pricing and Distribution; Integrated Promotion
MBA202 | Financial Management | 4 | T | Time Value of Money; Capital Budgeting; Capital Structure; Dividend Policy; Working Capital
MBA203 | Human Resource Management | 3 | T | Talent Acquisition; Learning and Development; Performance Management; Compensation; Employee Relations
MBA204 | Operations Management | 3 | T | Operations Strategy; Capacity and Layout; Inventory and Supply Chain; Quality Management
MBA205 | Research Methodology | 3 | T | Research Design; Measurement and Scaling; Sampling; Data Analysis; Reporting
MBA206 | Business Analytics | 3 | T | Data and Decisions; Descriptive Analytics; Predictive Models; Visualisation and Storytelling
# 3
MBA301 | Strategic Management | 4 | T | Strategic Analysis; Competitive Advantage; Corporate Strategy; Strategy Execution; Strategic Control
MBA302 | Corporate Governance and Business Ethics | 3 | T | Governance Frameworks; Board and Stakeholders; Ethics in Business; Sustainability and CSR
MBA303 | Specialisation I | 3 | T | Core Concepts; Tools and Methods; Applications; Case Studies
MBA304 | Specialisation II | 3 | T | Core Concepts; Tools and Methods; Applications; Case Studies
MBA305 | Specialisation III | 3 | T | Core Concepts; Tools and Methods; Applications; Case Studies
MBA306 | Summer Internship | 4 | P | Placement; Work Log; Internship Report; Viva
# 4
MBA401 | Entrepreneurship and Innovation | 3 | T | Opportunity Recognition; Business Models; Funding; Scaling a Venture
MBA402 | International Business | 3 | T | Global Environment; Trade and Investment; Foreign Exchange; Global Strategy
MBA403 | Specialisation IV | 3 | T | Advanced Concepts; Applications; Case Studies; Trends
MBA404 | Specialisation V | 3 | T | Advanced Concepts; Applications; Case Studies; Trends
MBA405 | Dissertation or Capstone Project | 8 | P | Problem Definition; Fieldwork and Analysis; Findings and Recommendations; Report and Viva
"""

_RAW["DCSEH"] = """
# 1
DCS101 | Networking Fundamentals | 4 | T | Network Models; IP Addressing; Routing and Switching; Network Services; Wireless Networks
DCS102 | Operating System Security | 4 | T | Linux Administration; Windows Administration; User and Permission Management; Hardening and Patching
DCS103 | Cyber Security Fundamentals | 4 | T | Threat Landscape; Cryptography Basics; Authentication and Access Control; Security Policies; Risk Management
DCS104 | Security Lab I | 3 | P | Network Scanning; System Hardening; Log Analysis; Firewall Configuration
# 2
DCS201 | Ethical Hacking and Penetration Testing | 4 | T | Reconnaissance; Scanning and Enumeration; Exploitation; Web Application Attacks; Reporting
DCS202 | Digital Forensics | 4 | T | Forensic Process; Disk and Memory Forensics; Network Forensics; Evidence Handling
DCS203 | Cyber Law and Incident Response | 3 | T | Cyber Law and IT Act; Incident Handling; Malware Basics; Security Operations Basics
DCS204 | Capstone Project | 4 | P | Scoping; Assessment; Findings; Presentation
"""

_RAW["CSEH-ADV"] = """
# 1
CSA101 | Advanced Penetration Testing | 4 | T | Advanced Reconnaissance; Exploit Development Basics; Privilege Escalation; Post-Exploitation; Reporting
CSA102 | Cloud and Application Security | 4 | T | Cloud Threat Models; Secure Architecture; API and Web Security; Container Security; DevSecOps
CSA103 | Threat Intelligence and Security Operations | 3 | T | Threat Intelligence; SIEM and Monitoring; Detection Engineering; Incident Response
CSA104 | Security Lab | 3 | P | Attack Simulation; Detection Rules; Log Correlation; Cloud Hardening
# 2
CSA201 | Red and Blue Team Operations | 4 | T | Adversary Emulation; Defensive Strategy; Purple Teaming; Operations Planning
CSA202 | Malware Analysis and Digital Forensics | 4 | T | Static Analysis; Dynamic Analysis; Memory Forensics; Timeline Analysis
CSA203 | Vulnerability Assessment and Management | 3 | T | Scanning Methods; Risk Rating; Remediation Planning; Compliance and Audit
CSA204 | Capstone Project | 4 | P | Scoping; Assessment; Findings; Presentation
"""

_RAW["APP"] = """
# 1
APP101 | Python Foundations | 4 | T | Syntax and Data Types; Control Flow; Functions; Collections; Modules and Packages
APP102 | Object-Oriented Python | 4 | T | Classes and Objects; Inheritance; Special Methods; Exceptions; Testing
APP103 | Automation and Scripting | 3 | T | Files and Folders; Working with APIs; Scheduling Tasks; Web Scraping
APP104 | Web Development with Flask and Django | 4 | T | Routing and Views; Templates; Forms and Validation; Databases; Authentication
APP105 | Data Analysis with Pandas | 3 | T | Series and DataFrames; Cleaning Data; Grouping and Joining; Visualisation
APP106 | Capstone Project | 4 | P | Planning; Development; Deployment; Demonstration
"""

_RAW["FSD"] = """
# 1
FSD101 | Web Foundations | 3 | T | HTML5; CSS3 and Layout; Responsive Design; Accessibility
FSD102 | JavaScript | 4 | T | Language Basics; The DOM; Asynchronous JavaScript; Modules and Tooling
FSD103 | React | 4 | T | Components and Props; State and Hooks; Routing; Forms and Data Fetching
FSD104 | Node.js and Express | 4 | T | Node Basics; Express Routing; REST API Design; Authentication
FSD105 | Databases | 3 | T | SQL Fundamentals; MongoDB; Data Modelling; Connecting to Applications
FSD106 | Git, Docker and Deployment | 3 | T | Version Control; Containers; Continuous Delivery; Hosting
FSD107 | Capstone Project | 4 | P | Planning; Build; Deploy; Demonstration
"""


def _parse(text):
    out, sem = {}, None
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            sem = int(line[1:])
            out[sem] = []
            continue
        code, name, credits, kind, units = [p.strip() for p in line.split("|")]
        out[sem].append((code, name, int(credits), "Theory" if kind == "T" else "Practical",
                         [u.strip() for u in units.split(";")]))
    return out


SYLLABUS = {code: _parse(text) for code, text in _RAW.items()}

PROGRAMME_INFO = {
    "BCA": {"admission_fee": 10000,
            "overview": "A three-year degree that takes you from programming basics to building and deploying real software. Semesters one to four build the core of computing, and semesters five and six add AI, cloud and security, ending with a major project.",
            "careers": ["Software developer", "Web and mobile application developer", "Database administrator", "Software tester", "Higher studies such as MCA"],
            "outcomes": ["Write, test and debug programs in several languages", "Design and query relational databases", "Build web and mobile applications", "Explain the basics of AI, cloud and cyber security", "Plan and deliver a software project in a team"]},
    "BBA": {"admission_fee": 10000,
            "overview": "A three-year degree in business fundamentals: management, accounting, economics, marketing and people. Students choose a specialisation in the fifth semester and finish with a project and an internship.",
            "careers": ["Management trainee", "Marketing and sales executive", "Human resources executive", "Business analyst", "Higher studies such as MBA"],
            "outcomes": ["Apply core management and accounting concepts", "Analyse a business problem with data", "Communicate clearly in writing and in person", "Understand ethics and governance in business", "Plan a small venture"]},
    "BTECH-CSE": {"admission_fee": 20000,
            "overview": "A four-year engineering degree in computer science. Two years of mathematics, science and programming lead into algorithms, systems, networks, machine learning and security, with electives, training and a final-year project.",
            "careers": ["Software engineer", "Systems and network engineer", "Data engineer or scientist", "Security engineer", "Higher studies such as M.Tech"],
            "outcomes": ["Apply mathematics and science to computing problems", "Design efficient algorithms and software systems", "Build and secure networked applications", "Use machine learning on real data", "Work professionally and ethically in teams"]},
    "BAI": {"admission_fee": 15000,
            "overview": "A four-year degree that teaches artificial intelligence from first principles. Mathematics and Python come first, then machine learning, deep learning, language and vision, and finally deployment, ethics and a major project.",
            "careers": ["Machine learning engineer", "Data scientist", "AI application developer", "MLOps engineer", "Research and higher studies"],
            "outcomes": ["Use linear algebra, calculus and statistics for AI", "Build and evaluate machine learning models", "Create applications with language and vision models", "Deploy and monitor models in production", "Judge the fairness and safety of AI systems"]},
    "MCA": {"admission_fee": 12000,
            "overview": "A two-year postgraduate degree for graduates who want advanced software skills: data structures, databases, cloud, AI and DevOps, finishing with a dissertation or major project.",
            "careers": ["Senior software developer", "Cloud and DevOps engineer", "Data engineer", "Solutions architect", "Teaching and research"],
            "outcomes": ["Design and build enterprise-grade software", "Deploy applications on the cloud with automation", "Apply machine learning and big data tools", "Secure software and respond to incidents", "Carry out and report independent research"]},
    "MBA": {"admission_fee": 15000,
            "overview": "A two-year management degree for graduates from any discipline. The first year builds the core of management, finance, marketing, people and operations; the second year adds strategy, a chosen specialisation, an internship and a capstone.",
            "careers": ["Manager in operations, finance, marketing or HR", "Business consultant", "Product or project manager", "Entrepreneur", "Analyst"],
            "outcomes": ["Make decisions using financial and analytical tools", "Develop marketing, people and operations strategy", "Lead teams and manage change", "Apply ethics and governance in business", "Plan and launch a venture"]},
    "DCSEH": {"admission_fee": 6000,
            "overview": "A one-year diploma in cyber security and ethical hacking for school leavers and graduates. It combines networking and system security with hands-on attack, defence and forensic labs.",
            "careers": ["Security analyst", "Junior penetration tester", "SOC analyst", "IT support with a security focus", "Further study in security"],
            "outcomes": ["Secure networks and operating systems", "Find and report weaknesses ethically", "Collect and handle digital evidence", "Respond to security incidents", "Explain the cyber law basics"]},
    "CSEH-ADV": {"admission_fee": 6000,
            "overview": "A one-year advanced programme for people who already work with computers and want a security career. It covers advanced testing, cloud security, threat intelligence, red and blue team work and malware analysis.",
            "careers": ["Penetration tester", "Security operations analyst", "Cloud security engineer", "Threat analyst", "Digital forensics analyst"],
            "outcomes": ["Plan and run advanced penetration tests", "Secure cloud and application environments", "Detect and investigate threats", "Analyse malware safely", "Report findings clearly to decision makers"]},
    "APP": {"admission_fee": 3000,
            "overview": "A six-month certificate that takes you from solid Python basics to building and deploying applications: automation, web development and data analysis, finishing with a capstone project.",
            "careers": ["Python developer", "Automation engineer", "Data analyst", "Web developer", "Entry-level software roles"],
            "outcomes": ["Write clean, tested Python", "Automate everyday tasks", "Build a small web application", "Analyse data with Pandas", "Deploy and present a finished project"]},
    "FSD": {"admission_fee": 4000,
            "overview": "A six-month certificate in building complete web applications: the interface, the server, the database and deployment, with a capstone you can show to an employer.",
            "careers": ["Full-stack developer", "Front-end developer", "Back-end developer", "Freelance web developer", "Entry-level software roles"],
            "outcomes": ["Build responsive, accessible interfaces", "Create REST APIs with Node.js", "Design and use SQL and MongoDB databases", "Use Git and containers", "Deploy a complete application"]},
}


def total_credits(code):
    return sum(s[2] for subjects in SYLLABUS.get(code, {}).values() for s in subjects)
