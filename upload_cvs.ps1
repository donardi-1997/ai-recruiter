# ============================================================
# AI RECRUITER - MULTI CV UPLOAD
# ============================================================

$ErrorActionPreference = "Stop"

# ============================================================
# CONFIGURATION
# ============================================================

$API_URL = "https://ai.adrianguerra.net/api"

$CV_FOLDER = Join-Path $PSScriptRoot "test-cvs"

$COGNITO_CLIENT_ID = "buusqp2p10vb2nh8ft40i8imc"

$AWS_REGION = "us-east-2"

# Delay between candidates
$DELAY_SECONDS = 10

# ============================================================
# HEADER
# ============================================================

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AI RECRUITER - MULTI CV UPLOAD" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "API:"
Write-Host $API_URL
Write-Host ""

Write-Host "Carpeta:"
Write-Host $CV_FOLDER
Write-Host ""

# ============================================================
# FIND CVs
# ============================================================

$files = Get-ChildItem `
    -Path $CV_FOLDER `
    -Filter "*.pdf" `
    -File |
    Sort-Object Name

if ($files.Count -eq 0) {
    Write-Host "No se encontraron archivos PDF." -ForegroundColor Red
    exit 1
}

Write-Host "CVs encontrados: $($files.Count)" -ForegroundColor Green

foreach ($file in $files) {
    Write-Host "  - $($file.Name)"
}

Write-Host ""

# ============================================================
# COGNITO
# ============================================================

$username = Read-Host "Cognito username"

$passwordSecure = Read-Host "Cognito password" -AsSecureString

$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
    $passwordSecure
)

$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    $passwordPtr
)

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR(
    $passwordPtr
)

Write-Host ""

# ============================================================
# AUTHENTICATION
# ============================================================

Write-Host "Autenticando con Cognito..." -ForegroundColor Yellow

$authParameters = "USERNAME=$username,PASSWORD=$password"

try {

    $authResult = aws cognito-idp initiate-auth `
        --client-id $COGNITO_CLIENT_ID `
        --auth-flow USER_PASSWORD_AUTH `
        --auth-parameters $authParameters `
        --region $AWS_REGION `
        --output json |
        ConvertFrom-Json

}
catch {

    Write-Host ""
    Write-Host "ERROR autenticando con Cognito." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

if (-not $authResult.AuthenticationResult.AccessToken) {

    Write-Host ""
    Write-Host "No se obtuvo AccessToken." -ForegroundColor Red

    if ($authResult.ChallengeName) {
        Write-Host "Challenge: $($authResult.ChallengeName)" -ForegroundColor Yellow
    }

    exit 1
}

$TOKEN = $authResult.AuthenticationResult.AccessToken

Write-Host ""
Write-Host "Autenticación correcta." -ForegroundColor Green
Write-Host ""

# ============================================================
# TEST AUTH
# ============================================================

Write-Host "Probando autenticación contra API..." -ForegroundColor Yellow

try {

    $headers = @{
        Authorization = "Bearer $TOKEN"
    }

    $authTest = Invoke-RestMethod `
        -Uri "$API_URL/auth/me" `
        -Method Get `
        -Headers $headers

    Write-Host "API authentication OK." -ForegroundColor Green

}
catch {

    Write-Host ""
    Write-Host "API authentication FAILED." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================
# UPLOAD
# ============================================================

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " SUBIENDO CANDIDATOS" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$results = @()

$total = $files.Count
$counter = 0

foreach ($file in $files) {

    $counter++

    $candidateName = [System.IO.Path]::GetFileNameWithoutExtension(
        $file.Name
    )

    $fileSizeKB = [math]::Round(
        $file.Length / 1KB,
        2
    )

    Write-Host ""
    Write-Host "[$counter/$total] $candidateName" -ForegroundColor Cyan
    Write-Host "Archivo: $($file.Name)"
    Write-Host "Size: $fileSizeKB KB"

    # --------------------------------------------------------
    # WAIT BEFORE UPLOAD
    # --------------------------------------------------------

    if ($counter -gt 1) {

        Write-Host ""
        Write-Host "Esperando $DELAY_SECONDS segundos..." -ForegroundColor DarkYellow

        Start-Sleep -Seconds $DELAY_SECONDS
    }

    try {

        # ----------------------------------------------------
        # MULTIPART FORM
        # ----------------------------------------------------

        $form = @{
            name = $candidateName
            file = Get-Item $file.FullName
        }

        $response = Invoke-RestMethod `
            -Uri "$API_URL/candidates" `
            -Method Post `
            -Headers @{
                Authorization = "Bearer $TOKEN"
            } `
            -Form $form

        Write-Host "UPLOAD OK" -ForegroundColor Green

        $candidateId = $null

        if ($response.candidate) {
            $candidateId = $response.candidate.id
        }

        $results += [PSCustomObject]@{
            File        = $file.Name
            Candidate   = $candidateName
            Status      = "SUCCESS"
            CandidateId = $candidateId
        }

        # ----------------------------------------------------
        # WAIT AFTER SUCCESS
        # ----------------------------------------------------

        Write-Host ""
        Write-Host "Esperando $DELAY_SECONDS segundos antes del siguiente CV..." -ForegroundColor DarkYellow

        Start-Sleep -Seconds $DELAY_SECONDS

    }
    catch {

        Write-Host "UPLOAD FAILED" -ForegroundColor Red

        $errorMessage = $_.Exception.Message

        Write-Host $errorMessage -ForegroundColor Red

        # ----------------------------------------------------
        # TRY TO SHOW API ERROR BODY
        # ----------------------------------------------------

        if ($_.ErrorDetails.Message) {
            Write-Host ""
            Write-Host "API response:" -ForegroundColor Yellow
            Write-Host $_.ErrorDetails.Message -ForegroundColor Yellow
        }

        $results += [PSCustomObject]@{
            File        = $file.Name
            Candidate   = $candidateName
            Status      = "FAILED"
            CandidateId = $null
        }

        # ----------------------------------------------------
        # WAIT AFTER FAILURE
        # ----------------------------------------------------

        Write-Host ""
        Write-Host "Esperando $DELAY_SECONDS segundos..." -ForegroundColor DarkYellow

        Start-Sleep -Seconds $DELAY_SECONDS
    }
}

# ============================================================
# RESULTS
# ============================================================

Write-Host ""
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " RESULTADO" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$results | Format-Table -AutoSize

$successCount = @(
    $results | Where-Object {
        $_.Status -eq "SUCCESS"
    }
).Count

$failedCount = @(
    $results | Where-Object {
        $_.Status -eq "FAILED"
    }
).Count

Write-Host ""
Write-Host "Total:   $total"
Write-Host "Success: $successCount" -ForegroundColor Green
Write-Host "Failed:  $failedCount" -ForegroundColor Red
Write-Host ""

# ============================================================
# FINAL MESSAGE
# ============================================================

if ($failedCount -eq 0) {

    Write-Host "==============================================" -ForegroundColor Green
    Write-Host " TODOS LOS CVs FUERON SUBIDOS CORRECTAMENTE" -ForegroundColor Green
    Write-Host "==============================================" -ForegroundColor Green

}
else {

    Write-Host "==============================================" -ForegroundColor Yellow
    Write-Host " ALGUNOS CVs FALLARON" -ForegroundColor Yellow
    Write-Host "==============================================" -ForegroundColor Yellow
}

Write-Host ""
