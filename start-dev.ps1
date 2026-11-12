<#
.SYNOPSIS
    IntentLock Full-Stack Development Launcher (FastAPI Backend + Vite React Frontend)

.DESCRIPTION
    Starts both the IntentLock FastAPI Backend on http://localhost:8000
    and the Vite React TypeScript Frontend on http://localhost:5173.
    Automatically seeds the 15-SKU synthetic merchant catalog (MERCH-ACME-001),
    3 RBAC personas (Coordinator Alice, Approver Bob, Buyer Charlie),
    and 3 Coordinator Discovery Interview records on startup.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  IntentLock — Approval-Aware Purchasing Agent & PayPal Checkout" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path (Join-Path $BackendDir "app\main.py"))) {
    Write-Error "Backend directory not found at $BackendDir"
    exit 1
}

if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    Write-Error "Frontend directory not found at $FrontendDir"
    exit 1
}

# Copy root .env.example to backend/.env if backend/.env does not exist yet
$BackendEnv = Join-Path $BackendDir ".env"
$RootEnvExample = Join-Path $RepoRoot ".env.example"
if ((-not (Test-Path $BackendEnv)) -and (Test-Path $RootEnvExample)) {
    Copy-Item -Path $RootEnvExample -Destination $BackendEnv
    Write-Host "[Init] Created default backend/.env from .env.example" -ForegroundColor DarkGray
}

Write-Host "[1/2] Launching FastAPI Backend on http://localhost:8000 ..." -ForegroundColor Green
$BackendProcess = Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$BackendDir'; Write-Host 'Starting IntentLock FastAPI Server (http://localhost:8000)...' -ForegroundColor Green; python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
) -PassThru

Start-Sleep -Seconds 2

Write-Host "[2/2] Launching Vite React Frontend on http://localhost:5173 ..." -ForegroundColor Green
$FrontendProcess = Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$FrontendDir'; Write-Host 'Starting IntentLock Vite React UI (http://localhost:5173)...' -ForegroundColor Cyan; npm run dev -- --port 5173"
) -PassThru

Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  IntentLock is running!" -ForegroundColor Yellow
Write-Host "  -> Frontend UI:      http://localhost:5173" -ForegroundColor White
Write-Host "  -> FastAPI Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  -> OpenAPI Docs:     http://localhost:8000/docs" -ForegroundColor White
Write-Host "  -> Health Check:     http://localhost:8000/api/v1/health" -ForegroundColor White
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  Tip: Click 'LLM Router & PayPal Keys' in the top navbar to paste" -ForegroundColor Gray
Write-Host "       live Gemini/Groq/xAI/OpenRouter or PayPal Sandbox keys at runtime." -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Cyan
