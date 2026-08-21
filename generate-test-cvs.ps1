# ============================================================
# GENERAR 10 CVs FICTICIOS EN PDF
# AI Recruiter - Testing / MVP3
# ============================================================

$OutputDir = Join-Path $PWD "test-cvs"

# ------------------------------------------------------------
# Crear / limpiar carpeta
# ------------------------------------------------------------

if (Test-Path $OutputDir) {
    Remove-Item $OutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# ------------------------------------------------------------
# Datos de 10 candidatos NUEVOS
# ------------------------------------------------------------

$candidates = @(

    @{
        Name = "Camila Alejandra Rojas"
        Role = "Senior Backend Engineer"
        Email = "camila.rojas@example.com"
        Location = "Bogota, Colombia"

        Profile = "Ingeniera de software especializada en desarrollo backend y arquitecturas distribuidas. Experiencia construyendo APIs, servicios de alto rendimiento y soluciones cloud para plataformas empresariales."

        Experience = @(
            "Senior Backend Engineer - FintechPro | 2021 - 2026",
            "Desarrollo de microservicios utilizando Python, FastAPI y PostgreSQL.",
            "Diseño e implementacion de APIs REST para plataformas financieras.",
            "Implementacion de sistemas de procesamiento asincrono utilizando RabbitMQ.",
            "Optimización de consultas SQL y procesos de alto volumen.",
            "Implementacion de servicios en AWS utilizando ECS, RDS y SQS."
        )

        Skills = "Python, FastAPI, PostgreSQL, AWS, ECS, RDS, SQS, RabbitMQ, Docker, Microservices, REST APIs, Git"

        Education = "Ingenieria de Sistemas - Universidad Nacional de Colombia"
    },

    @{
        Name = "Mateo Sebastian Vargas"
        Role = "Frontend Engineer"
        Email = "mateo.vargas@example.com"
        Location = "Medellin, Colombia"

        Profile = "Frontend Engineer enfocado en crear aplicaciones web modernas, accesibles y de alto rendimiento. Experiencia trabajando con arquitecturas frontend escalables y equipos multidisciplinarios."

        Experience = @(
            "Frontend Engineer - PixelWorks | 2020 - 2026",
            "Desarrollo de aplicaciones web utilizando React y Next.js.",
            "Implementacion de interfaces utilizando TypeScript y Tailwind CSS.",
            "Construccion de componentes reutilizables y sistemas de diseño.",
            "Optimización del rendimiento de aplicaciones web.",
            "Integracion de aplicaciones frontend con APIs REST y GraphQL."
        )

        Skills = "React, Next.js, TypeScript, JavaScript, Tailwind CSS, GraphQL, REST APIs, Jest, Cypress, Git"

        Education = "Ingenieria de Software - Universidad EAFIT"
    },

    @{
        Name = "Juliana Marcela Torres"
        Role = "Data Scientist"
        Email = "juliana.torres@example.com"
        Location = "Cali, Colombia"

        Profile = "Data Scientist con experiencia en analisis de datos, machine learning y construccion de modelos predictivos. Especializada en transformar grandes conjuntos de datos en información accionable."

        Experience = @(
            "Data Scientist - AnalyticsLab | 2021 - 2026",
            "Construccion de modelos predictivos utilizando Python y Scikit-learn.",
            "Analisis exploratorio de datos utilizando Pandas y NumPy.",
            "Desarrollo de modelos de clasificación y regresión.",
            "Creacion de dashboards para equipos de negocio.",
            "Implementacion de pipelines de datos utilizando Python y SQL."
        )

        Skills = "Python, Pandas, NumPy, Scikit-learn, Machine Learning, SQL, Statistics, Jupyter, Power BI"

        Education = "Estadistica - Universidad del Valle"
    },

    @{
        Name = "Nicolas Felipe Castro"
        Role = "DevOps Engineer"
        Email = "nicolas.castro@example.com"
        Location = "Bogota, Colombia"

        Profile = "DevOps Engineer especializado en automatización, infraestructura como código y plataformas cloud. Experiencia diseñando pipelines CI/CD y administrando infraestructura para aplicaciones distribuidas."

        Experience = @(
            "DevOps Engineer - PlatformTech | 2019 - 2026",
            "Diseño y mantenimiento de pipelines CI/CD.",
            "Automatizacion de infraestructura utilizando Terraform.",
            "Administracion de clusters Kubernetes.",
            "Construccion y administración de imágenes Docker.",
            "Implementacion de monitoreo utilizando Prometheus y Grafana.",
            "Administracion de infraestructura AWS y Linux."
        )

        Skills = "AWS, Terraform, Kubernetes, Docker, GitHub Actions, Jenkins, Linux, Prometheus, Grafana, CI/CD"

        Education = "Ingenieria Informatica - Universidad Javeriana"
    },

    @{
        Name = "Sara Valentina Mendoza"
        Role = "Machine Learning Engineer"
        Email = "sara.mendoza@example.com"
        Location = "Barranquilla, Colombia"

        Profile = "Machine Learning Engineer especializada en desarrollo y despliegue de modelos de inteligencia artificial. Experiencia en procesamiento de datos, entrenamiento de modelos y aplicaciones de NLP."

        Experience = @(
            "Machine Learning Engineer - AI Solutions | 2022 - 2026",
            "Desarrollo de modelos de Machine Learning utilizando Python.",
            "Implementacion de modelos de clasificación y procesamiento de lenguaje natural.",
            "Construccion de pipelines de entrenamiento.",
            "Desarrollo de APIs para servir modelos de Machine Learning.",
            "Despliegue de modelos utilizando AWS SageMaker.",
            "Evaluacion y monitoreo del rendimiento de modelos."
        )

        Skills = "Python, Machine Learning, NLP, Scikit-learn, PyTorch, Pandas, NumPy, AWS SageMaker, FastAPI, SQL"

        Education = "Ingenieria de Sistemas - Universidad del Norte"
    },

    @{
        Name = "Felipe Andres Navarro"
        Role = "Cloud Solutions Architect"
        Email = "felipe.navarro@example.com"
        Location = "Medellin, Colombia"

        Profile = "Cloud Solutions Architect con experiencia diseñando arquitecturas escalables, seguras y altamente disponibles en AWS. Especializado en arquitecturas serverless y sistemas distribuidos."

        Experience = @(
            "Cloud Solutions Architect - CloudExperts | 2018 - 2026",
            "Diseño de arquitecturas empresariales sobre AWS.",
            "Implementacion de soluciones serverless utilizando Lambda y API Gateway.",
            "Diseño de arquitecturas utilizando DynamoDB y S3.",
            "Configuracion de VPC, IAM, CloudWatch y Load Balancers.",
            "Migracion de aplicaciones tradicionales hacia arquitecturas cloud.",
            "Definicion de estrategias de alta disponibilidad y recuperación."
        )

        Skills = "AWS, Lambda, API Gateway, DynamoDB, S3, VPC, IAM, CloudWatch, ECS, Load Balancing, Serverless"

        Education = "Ingenieria de Sistemas - Universidad Pontificia Bolivariana"
    },

    @{
        Name = "Manuela Sofia Restrepo"
        Role = "QA Automation Engineer"
        Email = "manuela.restrepo@example.com"
        Location = "Bogota, Colombia"

        Profile = "QA Automation Engineer especializada en automatización de pruebas funcionales, APIs y aplicaciones web. Experiencia implementando estrategias de calidad y pruebas automatizadas."

        Experience = @(
            "QA Automation Engineer - QualityFirst | 2020 - 2026",
            "Diseño de estrategias de automatización para aplicaciones web.",
            "Desarrollo de pruebas utilizando Playwright y Selenium.",
            "Automatización de pruebas de APIs REST.",
            "Implementacion de pruebas de regresion.",
            "Integracion de pruebas automatizadas en pipelines CI/CD.",
            "Creacion de reportes de calidad y seguimiento de defectos."
        )

        Skills = "Playwright, Selenium, Python, Java, Postman, REST APIs, SQL, GitHub Actions, CI/CD, QA"

        Education = "Ingenieria de Sistemas - Universidad de La Salle"
    },

    @{
        Name = "David Alejandro Molina"
        Role = "Java Software Engineer"
        Email = "david.molina@example.com"
        Location = "Cali, Colombia"

        Profile = "Software Engineer especializado en desarrollo backend con Java y Spring Boot. Experiencia construyendo aplicaciones empresariales, APIs REST y sistemas distribuidos."

        Experience = @(
            "Java Software Engineer - EnterpriseApps | 2019 - 2026",
            "Desarrollo de aplicaciones empresariales utilizando Java y Spring Boot.",
            "Construccion de APIs REST y servicios backend.",
            "Implementacion de arquitecturas basadas en microservicios.",
            "Integracion con PostgreSQL y MySQL.",
            "Implementacion de pruebas unitarias utilizando JUnit.",
            "Despliegue de aplicaciones utilizando Docker."
        )

        Skills = "Java, Spring Boot, Spring, REST APIs, PostgreSQL, MySQL, JUnit, Docker, Maven, Microservices"

        Education = "Ingenieria de Sistemas - Universidad Autonoma de Occidente"
    },

    @{
        Name = "Laura Isabel Quintero"
        Role = "Data Engineer"
        Email = "laura.quintero@example.com"
        Location = "Cartagena, Colombia"

        Profile = "Data Engineer especializada en construcción de pipelines de datos y plataformas analíticas. Experiencia trabajando con procesamiento de grandes volúmenes de información y servicios cloud."

        Experience = @(
            "Data Engineer - DataPlatform | 2021 - 2026",
            "Construccion de pipelines ETL y ELT.",
            "Desarrollo de procesos de datos utilizando Python y SQL.",
            "Implementacion de soluciones utilizando Apache Spark.",
            "Construccion de data lakes utilizando Amazon S3.",
            "Implementacion de procesos analiticos utilizando AWS Glue y Athena.",
            "Optimización de procesos de procesamiento de datos."
        )

        Skills = "Python, SQL, Apache Spark, AWS Glue, S3, Athena, Redshift, ETL, Data Lakes, Pandas"

        Education = "Ingenieria de Sistemas - Universidad Tecnologica de Bolivar"
    },

    @{
        Name = "Juan Pablo Cardenas"
        Role = "Full Stack Engineer"
        Email = "juan.cardenas@example.com"
        Location = "Bucaramanga, Colombia"

        Profile = "Full Stack Engineer con experiencia desarrollando aplicaciones web completas desde frontend hasta backend. Experiencia trabajando con JavaScript, React, Node.js y bases de datos relacionales."

        Experience = @(
            "Full Stack Engineer - AppFactory | 2020 - 2026",
            "Desarrollo de aplicaciones web utilizando React y Node.js.",
            "Construccion de APIs REST utilizando Express.",
            "Diseño e implementacion de bases de datos PostgreSQL.",
            "Implementacion de autenticacion utilizando JWT.",
            "Desarrollo de interfaces responsivas.",
            "Despliegue de aplicaciones utilizando Docker y AWS."
        )

        Skills = "React, Node.js, Express, JavaScript, TypeScript, PostgreSQL, JWT, Docker, AWS, REST APIs"

        Education = "Ingenieria de Sistemas - Universidad Industrial de Santander"
    }
)

# ------------------------------------------------------------
# Inicializar Microsoft Word
# ------------------------------------------------------------

try {

    $word = New-Object -ComObject Word.Application

    $word.Visible = $false
    $word.DisplayAlerts = 0

    foreach ($candidate in $candidates) {

        Write-Host ""
        Write-Host "Generando: $($candidate.Name)" -ForegroundColor Cyan

        $document = $null

        try {

            $document = $word.Documents.Add()

            $selection = $word.Selection

            # ------------------------------------------------
            # NOMBRE
            # ------------------------------------------------

            $selection.Font.Name = "Arial"
            $selection.Font.Size = 20
            $selection.Font.Bold = $true

            $selection.TypeText($candidate.Name)
            $selection.TypeParagraph()

            # ------------------------------------------------
            # CARGO
            # ------------------------------------------------

            $selection.Font.Size = 13
            $selection.Font.Bold = $false

            $selection.TypeText($candidate.Role)
            $selection.TypeParagraph()

            # ------------------------------------------------
            # DATOS
            # ------------------------------------------------

            $selection.Font.Size = 10

            $selection.TypeText(
                "$($candidate.Email) | $($candidate.Location)"
            )

            $selection.TypeParagraph()
            $selection.TypeParagraph()

            # ------------------------------------------------
            # PERFIL
            # ------------------------------------------------

            $selection.Font.Size = 14
            $selection.Font.Bold = $true

            $selection.TypeText("PERFIL")
            $selection.TypeParagraph()

            $selection.Font.Size = 10
            $selection.Font.Bold = $false

            $selection.TypeText($candidate.Profile)

            $selection.TypeParagraph()
            $selection.TypeParagraph()

            # ------------------------------------------------
            # EXPERIENCIA
            # ------------------------------------------------

            $selection.Font.Size = 14
            $selection.Font.Bold = $true

            $selection.TypeText("EXPERIENCIA")
            $selection.TypeParagraph()

            $selection.Font.Size = 10
            $selection.Font.Bold = $false

            foreach ($line in $candidate.Experience) {

                $selection.TypeText($line)
                $selection.TypeParagraph()
            }

            $selection.TypeParagraph()

            # ------------------------------------------------
            # HABILIDADES
            # ------------------------------------------------

            $selection.Font.Size = 14
            $selection.Font.Bold = $true

            $selection.TypeText("HABILIDADES")
            $selection.TypeParagraph()

            $selection.Font.Size = 10
            $selection.Font.Bold = $false

            $selection.TypeText($candidate.Skills)

            $selection.TypeParagraph()
            $selection.TypeParagraph()

            # ------------------------------------------------
            # EDUCACION
            # ------------------------------------------------

            $selection.Font.Size = 14
            $selection.Font.Bold = $true

            $selection.TypeText("EDUCACION")
            $selection.TypeParagraph()

            $selection.Font.Size = 10
            $selection.Font.Bold = $false

            $selection.TypeText($candidate.Education)

            # ------------------------------------------------
            # NOMBRE DEL PDF
            # ------------------------------------------------

            $safeName = $candidate.Name -replace '[^a-zA-Z0-9 ]', ''
            $safeName = $safeName -replace '\s+', '_'

            $pdfPath = Join-Path $OutputDir "$safeName.pdf"

            # ------------------------------------------------
            # EXPORTAR PDF
            # 17 = wdExportFormatPDF
            # ------------------------------------------------

            $document.ExportAsFixedFormat(
                $pdfPath,
                17
            )

            Write-Host "  OK -> $pdfPath" -ForegroundColor Green

        }
        catch {

            Write-Host ""
            Write-Host "  ERROR generando $($candidate.Name)" -ForegroundColor Red
            Write-Host $_.Exception.Message -ForegroundColor Red
        }
        finally {

            if ($null -ne $document) {

                try {
                    $document.Close($false)
                }
                catch {
                }
            }
        }
    }
}
finally {

    if ($null -ne $word) {

        try {
            $word.Quit()
        }
        catch {
        }

        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) |
            Out-Null
    }
}

# ------------------------------------------------------------
# RESULTADO
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "CVs generados correctamente" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

$files = Get-ChildItem $OutputDir -Filter "*.pdf"

Write-Host "Total: $($files.Count) PDFs" -ForegroundColor Cyan
Write-Host ""

Write-Host "Carpeta:" -ForegroundColor Yellow
Write-Host $OutputDir
Write-Host ""

$files |
    Select-Object Name,
                  @{Name="KB";Expression={[math]::Round($_.Length / 1KB, 2)}} |
    Format-Table -AutoSize