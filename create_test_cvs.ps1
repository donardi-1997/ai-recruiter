# ============================================================
# CREATE TEST CVS
# AI RECRUITER
# ============================================================

$OutputDir = ".\test_cvs"

New-Item `
    -ItemType Directory `
    -Force `
    -Path $OutputDir | Out-Null


# ============================================================
# PYTHON SCRIPT
# ============================================================

$PythonScript = @'
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    ListFlowable,
    ListItem
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import os


OUTPUT_DIR = "test_cvs"

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


# ============================================================
# STYLES
# ============================================================

styles = getSampleStyleSheet()

title_style = styles["Title"]

title_style.fontName = "Helvetica-Bold"
title_style.fontSize = 22
title_style.leading = 26
title_style.alignment = TA_LEFT

subtitle_style = styles["Heading2"]

subtitle_style.fontName = "Helvetica-Bold"
subtitle_style.fontSize = 14
subtitle_style.leading = 18

body_style = styles["BodyText"]

body_style.fontName = "Helvetica"
body_style.fontSize = 10
body_style.leading = 14

small_style = styles["BodyText"]

small_style.fontName = "Helvetica"
small_style.fontSize = 9
small_style.leading = 12


# ============================================================
# FUNCTION
# ============================================================

def create_pdf(
    filename,
    name,
    headline,
    location,
    email,
    summary,
    experience,
    skills,
    education
):

    path = os.path.join(
        OUTPUT_DIR,
        filename
    )

    document = SimpleDocTemplate(
        path,
        pagesize=LETTER,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45
    )

    story = []


    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    story.append(
        Paragraph(
            name,
            title_style
        )
    )

    story.append(
        Spacer(
            1,
            6
        )
    )

    story.append(
        Paragraph(
            headline,
            subtitle_style
        )
    )

    story.append(
        Spacer(
            1,
            4
        )
    )

    story.append(
        Paragraph(
            f"{location} | {email}",
            small_style
        )
    )

    story.append(
        Spacer(
            1,
            15
        )
    )


    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Professional Summary",
            subtitle_style
        )
    )

    story.append(
        Spacer(
            1,
            5
        )
    )

    story.append(
        Paragraph(
            summary,
            body_style
        )
    )

    story.append(
        Spacer(
            1,
            15
        )
    )


    # --------------------------------------------------------
    # EXPERIENCE
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Professional Experience",
            subtitle_style
        )
    )

    story.append(
        Spacer(
            1,
            5
        )
    )

    for item in experience:

        story.append(
            Paragraph(
                f"<b>{item['title']}</b>",
                body_style
            )
        )

        story.append(
            Paragraph(
                item["period"],
                small_style
            )
        )

        story.append(
            Spacer(
                1,
                3
            )
        )

        bullets = []

        for bullet in item["bullets"]:

            bullets.append(
                ListItem(
                    Paragraph(
                        bullet,
                        body_style
                    )
                )
            )

        story.append(
            ListFlowable(
                bullets,
                bulletType="bullet",
                leftIndent=20
            )
        )

        story.append(
            Spacer(
                1,
                10
            )
        )


    # --------------------------------------------------------
    # SKILLS
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Technical Skills",
            subtitle_style
        )
    )

    story.append(
        Spacer(
            1,
            5
        )
    )

    skill_items = []

    for skill in skills:

        skill_items.append(
            ListItem(
                Paragraph(
                    skill,
                    body_style
                )
            )
        )

    story.append(
        ListFlowable(
            skill_items,
            bulletType="bullet",
            leftIndent=20
        )
    )

    story.append(
        Spacer(
            1,
            15
        )
    )


    # --------------------------------------------------------
    # EDUCATION
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Education",
            subtitle_style
        )
    )

    story.append(
        Spacer(
            1,
            5
        )
    )

    story.append(
        Paragraph(
            education,
            body_style
        )
    )


    document.build(
        story
    )

    print(
        f"Created: {path}"
    )


# ============================================================
# 1. CARLOS MENDOZA
# ============================================================

create_pdf(

    "Carlos_Mendoza.pdf",

    "Carlos Mendoza",

    "Frontend Developer | React | TypeScript | AWS",

    "Bogota, Colombia",

    "carlos.mendoza@example.com",

    """
    Frontend Developer with 5 years of professional experience
    building scalable web applications using React, TypeScript,
    JavaScript, HTML, CSS and modern frontend architectures.
    Experienced with REST APIs, Git, Agile methodologies and AWS.
    """,

    [
        {
            "title":
                "Senior Frontend Developer - Tech Solutions",

            "period":
                "2022 - 2026",

            "bullets": [
                "Designed and developed scalable React applications.",
                "Built reusable components using TypeScript.",
                "Implemented responsive interfaces using HTML and CSS.",
                "Integrated REST APIs with frontend applications.",
                "Used AWS Lambda, API Gateway and S3.",
                "Worked with Git and GitHub using pull requests and code reviews.",
                "Participated in Scrum ceremonies and Agile development."
            ]
        }
    ],

    [
        "React",
        "TypeScript",
        "JavaScript",
        "HTML5",
        "CSS3",
        "REST APIs",
        "AWS Lambda",
        "AWS API Gateway",
        "AWS S3",
        "Git / GitHub"
    ],

    "Bachelor of Software Engineering"
)


# ============================================================
# 2. LAURA GOMEZ
# ============================================================

create_pdf(

    "Laura_Gomez.pdf",

    "Laura Gómez",

    "Frontend Developer | React | Angular",

    "Medellin, Colombia",

    "laura.gomez@example.com",

    """
    Frontend Developer with 3 years of experience developing web
    applications with React and Angular. Strong JavaScript knowledge,
    experience consuming REST APIs and working with Agile teams.
    Limited professional experience with AWS cloud services.
    """,

    [
        {
            "title":
                "Frontend Developer - Digital Apps",

            "period":
                "2023 - 2026",

            "bullets": [
                "Developed web applications using React.",
                "Maintained Angular applications.",
                "Created reusable JavaScript components.",
                "Consumed REST APIs.",
                "Implemented responsive user interfaces.",
                "Participated in Scrum development teams.",
                "Used Git and GitHub for source control."
            ]
        }
    ],

    [
        "React",
        "Angular",
        "JavaScript",
        "TypeScript",
        "HTML",
        "CSS",
        "REST APIs",
        "Git"
    ],

    "Bachelor of Computer Science"
)


# ============================================================
# 3. MATEO RODRIGUEZ
# ============================================================

create_pdf(

    "Mateo_Rodriguez.pdf",

    "Mateo Rodríguez",

    "Fullstack Developer | React | Node.js | AWS",

    "Bogota, Colombia",

    "mateo.rodriguez@example.com",

    """
    Fullstack Developer with 6 years of experience developing
    modern web applications. Specialized in React, JavaScript,
    Node.js, REST APIs and AWS architecture. Experienced in
    cloud-native applications, Agile methodologies and software
    engineering best practices.
    """,

    [
        {
            "title":
                "Fullstack Developer - Cloud Systems",

            "period":
                "2020 - 2026",

            "bullets": [
                "Developed frontend applications using React and TypeScript.",
                "Built backend services using Node.js.",
                "Designed and consumed REST APIs.",
                "Implemented AWS Lambda serverless functions.",
                "Configured AWS API Gateway.",
                "Used DynamoDB and S3 for cloud applications.",
                "Implemented authentication and authorization.",
                "Used Git and GitHub with code review workflows.",
                "Worked in Scrum and Kanban teams."
            ]
        }
    ],

    [
        "React",
        "JavaScript",
        "TypeScript",
        "Node.js",
        "HTML",
        "CSS",
        "REST APIs",
        "AWS Lambda",
        "AWS API Gateway",
        "AWS DynamoDB",
        "AWS S3",
        "Git"
    ],

    "Bachelor of Software Engineering"
)


# ============================================================
# 4. SOFIA MARTINEZ
# ============================================================

create_pdf(

    "Sofia_Martinez.pdf",

    "Sofía Martínez",

    "Junior Web Developer | HTML | CSS | JavaScript",

    "Tunja, Colombia",

    "sofia.martinez@example.com",

    """
    Junior Web Developer with 1 year of experience creating
    websites and simple web applications. Strong foundation in
    HTML, CSS and JavaScript. Currently learning React and modern
    frontend development practices.
    """,

    [
        {
            "title":
                "Junior Web Developer - Web Studio",

            "period":
                "2025 - 2026",

            "bullets": [
                "Created responsive websites using HTML and CSS.",
                "Developed interactive components using JavaScript.",
                "Maintained existing web pages.",
                "Worked with basic REST API integrations.",
                "Used Git for source control."
            ]
        }
    ],

    [
        "HTML",
        "CSS",
        "JavaScript",
        "Basic React",
        "Basic REST APIs",
        "Git"
    ],

    "Technical Degree in Web Development"
)


# ============================================================
# 5. DANIEL TORRES
# ============================================================

create_pdf(

    "Daniel_Torres.pdf",

    "Daniel Torres",

    "Backend Developer | Python | Java | AWS",

    "Cali, Colombia",

    "daniel.torres@example.com",

    """
    Backend Developer with 5 years of experience developing APIs,
    microservices and cloud applications. Specialized in Python,
    Java, databases and AWS. Limited professional experience with
    frontend technologies.
    """,

    [
        {
            "title":
                "Backend Developer - Enterprise Systems",

            "period":
                "2021 - 2026",

            "bullets": [
                "Developed backend services using Python.",
                "Built REST APIs and microservices.",
                "Developed Java applications.",
                "Worked with PostgreSQL and MySQL.",
                "Implemented AWS Lambda functions.",
                "Used AWS API Gateway.",
                "Worked with AWS S3 and DynamoDB.",
                "Used Git and CI/CD pipelines."
            ]
        }
    ],

    [
        "Python",
        "Java",
        "REST APIs",
        "AWS Lambda",
        "AWS API Gateway",
        "AWS S3",
        "AWS DynamoDB",
        "PostgreSQL",
        "Git"
    ],

    "Bachelor of Computer Engineering"
)


print("")
print("============================================")
print(" TEST CV GENERATION COMPLETE")
print("============================================")

'@


# ============================================================
# SAVE PYTHON SCRIPT
# ============================================================

$TempPython = ".\generate_test_cvs.py"

Set-Content `
    -Path $TempPython `
    -Value $PythonScript `
    -Encoding UTF8


# ============================================================
# RUN PYTHON
# ============================================================

python $TempPython


# ============================================================
# CLEANUP
# ============================================================

Remove-Item `
    $TempPython `
    -Force `
    -ErrorAction SilentlyContinue


# ============================================================
# VERIFY
# ============================================================

Write-Host ""
Write-Host "Generated files:" -ForegroundColor Cyan

Get-ChildItem `
    $OutputDir `
    -Filter "*.pdf" |
    Select-Object Name, Length |
    Format-Table -AutoSize