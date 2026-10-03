"""Generate clearly labeled synthetic resume fixtures for manual app testing."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "Test Resume" / "Edge Cases"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NAVY = colors.HexColor("#17324D")
TEAL = colors.HexColor("#0B7A75")
GRAY = colors.HexColor("#555555")


def styles():
    base = getSampleStyleSheet()
    return {
        "fixture": ParagraphStyle(
            "fixture",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#8A4B08"),
            alignment=TA_CENTER,
            spaceAfter=5,
        ),
        "name": ParagraphStyle(
            "name",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=20,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=1,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "contact",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=GRAY,
            alignment=TA_CENTER,
            spaceAfter=5,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=NAVY,
            spaceBefore=5,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.7,
            textColor=colors.HexColor("#222222"),
            spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.7,
            leftIndent=10,
            firstLineIndent=-6,
            spaceAfter=1.5,
        ),
    }


def add_section(story, label, style):
    story.append(Paragraph(label.upper(), style))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.45,
            color=colors.HexColor("#AAB8C2"),
            spaceAfter=2,
        )
    )


def build_resume(
    filename,
    fixture_label,
    name,
    title,
    contact,
    summary,
    skills,
    experience,
    education,
    extra_sections=None,
):
    path = OUTPUT_DIR / filename
    s = styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=f"{name} synthetic test resume",
        author="Synthetic app test fixture",
    )
    story = [
        Paragraph(fixture_label, s["fixture"]),
        Paragraph(name, s["name"]),
        Paragraph(title, s["title"]),
        Paragraph(contact, s["contact"]),
        HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=2),
    ]
    add_section(story, "Professional Summary", s["section"])
    story.append(Paragraph(summary, s["body"]))
    add_section(story, "Technical Skills", s["section"])
    for label, value in skills:
        story.append(Paragraph(f"<b>{label}:</b> {value}", s["body"]))
    add_section(story, "Professional Experience", s["section"])
    for role, dates, bullets in experience:
        story.append(Paragraph(f"<b>{role}</b> | <font color='#555555'>{dates}</font>", s["body"]))
        for bullet in bullets:
            story.append(Paragraph(f"• {bullet}", s["bullet"]))
        story.append(Spacer(1, 1))
    for label, paragraphs in extra_sections or []:
        add_section(story, label, s["section"])
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph, s["bullet"]))
    add_section(story, "Education", s["section"])
    for item in education:
        story.append(Paragraph(item, s["body"]))
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Synthetic test fixture. Content is adapted solely to exercise application "
            "scoring paths and must not be used for an employment decision.",
            s["fixture"],
        )
    )
    doc.build(story)
    return path


def build_image_only_resume():
    image_path = OUTPUT_DIR / "_image_only_source.png"
    pdf_path = OUTPUT_DIR / "EDGE_Image_Only_Resume.pdf"
    image = Image.new("RGB", (1275, 1650), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    draw.multiline_text(
        (90, 100),
        "IMAGE-ONLY RESUME TEST FIXTURE\n\n"
        "No selectable text exists in this PDF.\n"
        "Expected result: parsing_status = failed with an OCR guidance message.",
        fill="black",
        font=font,
        spacing=18,
    )
    image.save(image_path)
    image.save(pdf_path, "PDF", resolution=150)
    image_path.unlink()
    return pdf_path


def build_corrupted_resume():
    path = OUTPUT_DIR / "EDGE_Corrupted_Resume.pdf"
    path.write_bytes(b"%PDF-1.4\nThis file is intentionally truncated.")
    return path


def main():
    generated = []
    generated.append(
        build_resume(
            filename="arun_resume.pdf",
            fixture_label="SYNTHETIC TEST FIXTURE — ADJACENT / PARTIAL MATCH",
            name="Arunkumar Muthusamy",
            title="Senior Software Engineer | Backend & Data Engineering",
            contact=(
                "Buffalo, NY | +1-716-939-9968 | arunmuthu.ns@gmail.com<br/>"
                "https://linkedin.com/in/arun-muthu-ns"
            ),
            summary=(
                "Software engineer with 7+ years of professional software engineering "
                "experience building backend services, event-driven systems, and data "
                "processing workflows. Built limited prototype applications for RAG search "
                "and LLM document summarization, but has not deployed production generative "
                "AI or multi-agent systems. Strong adjacent experience in Python, Apache "
                "Spark, AWS, and distributed systems."
            ),
            skills=[
                ("Languages", "Java, Python, SQL, Rust, JavaScript, R"),
                (
                    "Backend & Data",
                    "Spring Boot, Spring WebFlux, REST APIs, Kafka, MongoDB, "
                    "Apache Spark, PySpark, Apache Airflow",
                ),
                (
                    "Cloud & Delivery",
                    "AWS EMR, S3, Athena, Glue, Lambda, EC2, SQS, SNS, Docker, "
                    "Kubernetes, Jenkins, Terraform",
                ),
            ],
            experience=[
                (
                    "Software Engineer Intern — Tarka Labs",
                    "Jun 2022 – Aug 2022",
                    [
                        "Integrated Slack OAuth, JWT, Rust, and React, reducing user-authentication management effort by 50%.",
                    ],
                ),
                (
                    "Senior Software Engineer — Sahaj Software Solutions",
                    "May 2019 – Jul 2021",
                    [
                        "Designed Java and Spring WebFlux facade services across Salesforce instances and built low-latency CometD event processing.",
                        "Built an end-to-end data and AI pipeline using Python, SQL, Airflow, Apache Spark, and AWS EMR; increased existing service test coverage to 90%.",
                        "Built event-driven REST microservices with Java, Spring Boot, MongoDB, and Kafka.",
                    ],
                ),
                (
                    "Member of Technical Staff — Zoho Corporation",
                    "Jun 2016 – May 2019",
                    [
                        "Led report-feature development using Java, Apache Struts, and MySQL and mentored a software engineering team.",
                    ],
                ),
            ],
            education=[
                "<b>State University of New York at Buffalo</b> — Master in Data Science | Aug 2021 – Dec 2022",
                "<b>Jeppiaar Engineering College, Anna University</b> — Bachelor of Technology in Information Technology | Aug 2012 – May 2016",
            ],
            extra_sections=[
                (
                    "Relevant Projects",
                    [
                        "Course Recommendation System — Developed a PySpark KNN recommendation analysis reporting 70% accuracy.",
                        "Market Basket Analysis — Performed RFM segmentation and Apriori recommendations in R with a Shiny dashboard.",
                        "Prototype RAG Search — Built a classroom retrieval-augmented generation prototype using Python, FAISS vector search, and Streamlit; not deployed to production.",
                        "LLM Document Summarizer — Built a limited Python prototype that used an LLM to summarize documents; no production monitoring or deployment.",
                    ],
                )
            ],
        )
    )
    generated.append(
        build_resume(
            filename="CV_BASELINE_FALL_2026.pdf",
            fixture_label="SYNTHETIC TEST FIXTURE — HARD REQUIREMENT GAP / UNKNOWN EVIDENCE",
            name="Iker J. Perez Omar",
            title="Mechanical Engineering Graduate Student | Optimization & Robotics",
            contact=(
                "Boston, MA | (470) 408-1915 | perezomar.i@northeastern.edu<br/>"
                "https://www.linkedin.com/in/iker-j-perez"
            ),
            summary=(
                "Engineer with 1 year of professional AI and engineering experience in "
                "optimization, simulation, robotics, and experimental research. Strong "
                "Python, C/C++, numerical methods, and genetic-algorithm experience; no "
                "demonstrated production experience with RAG, LangChain, LangGraph, vector "
                "databases, Microsoft Fabric, Azure AI Foundry, Snowflake, or Power BI."
            ),
            skills=[
                ("Software", "Python, NumPy, SciPy, pandas, SQL, C/C++, STM32"),
                (
                    "Engineering",
                    "Optimization, genetic algorithms, simulation, control theory, "
                    "microcontrollers, numerical methods, experimental design",
                ),
                ("AI Coursework", "BCG AI Fluency, Google AI and Productivity, MIT Introduction to Generative AI"),
            ],
            experience=[
                (
                    "Delivery AI Product Intern — BCG X",
                    "Feb 2026 – Aug 2026",
                    [
                        "Owned optimization components for a genetic-algorithm scheduler across an oil-and-gas logistics network.",
                        "Reduced simulation runtime from 60 to 6 minutes through profiling and algorithmic restructuring.",
                        "Refined model constraints and conflict prediction, supporting unmet demand below 1% in the test scenario.",
                    ],
                ),
                (
                    "Undergraduate Research Team Leader — Georgia Tech M.A.R.S. VIP",
                    "Jan 2025 – May 2025",
                    [
                        "Led experimental research and built a wind tunnel that increased measured peak voltage by 124%.",
                        "Built an autonomous STM32 robot with I2C sensors and PID control.",
                    ],
                ),
            ],
            education=[
                "<b>Northeastern University</b> — MS Mechanical Engineering | Sep 2026 – Expected May 2028",
                "<b>Universidad Carlos III de Madrid</b> — BS Engineering Physics, GPA 9.42/10 | Sep 2022 – Jun 2026",
                "<b>Georgia Institute of Technology</b> — Physics Exchange Program, GPA 4.0/4.0 | Aug 2024 – May 2025",
            ],
        )
    )
    generated.append(
        build_resume(
            filename="EDGE_Conflicting_Evidence.pdf",
            fixture_label="SYNTHETIC TEST FIXTURE — CONFLICTING EVIDENCE",
            name="Jordan Test Candidate",
            title="Applied AI Engineer",
            contact="test-candidate@example.com",
            summary=(
                "This fictional fixture intentionally contains directly conflicting "
                "statements so the app can exercise its conflict-handling path."
            ),
            skills=[("Claimed Skills", "Python, RAG, LangChain, vector databases")],
            experience=[
                (
                    "Candidate-provided experience statement",
                    "Current",
                    [
                        "Claims 5 years of production RAG deployment experience using LangChain and vector databases.",
                    ],
                ),
                (
                    "Verified employment record included for conflict testing",
                    "Current",
                    [
                        "States that the candidate has no production RAG deployments and completed only one classroom tutorial.",
                    ],
                ),
            ],
            education=["<b>Example University</b> — BS Computer Science"],
        )
    )
    generated.append(build_image_only_resume())
    generated.append(build_corrupted_resume())
    for path in generated:
        print(path)


if __name__ == "__main__":
    main()
