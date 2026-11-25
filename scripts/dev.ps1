<#
.SYNOPSIS
    Development runner for Life-API.
.DESCRIPTION
    Activates virtual environment, verifies or starts database container,
    and starts the Uvicorn API server on 127.0.0.1:8000 (or the Streamlit dashboard
    on 127.0.0.1:8501 with -Dashboard).
#>
[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Dashboard,
    [int]$DashboardPort = 8501
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

Set-Location $RootDir
Write-Host "==> Project Root: $RootDir"

# 1. Virtual environment activation
$VenvActivate = Join-Path $RootDir ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    Write-Host "==> Activating virtual environment..."
    . $VenvActivate
} else {
    Write-Host "==> No .venv found at $VenvActivate. Using current Python environment."
}

# 2. Database container check / start
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    Write-Host "==> Starting database container via docker compose..."
    docker compose up -d db
    Write-Host "==> Waiting for database container to be healthy..."
    $maxAttempts = 30
    $attempt = 0
    $healthy = $false
    while ($attempt -lt $maxAttempts) {
        $attempt++
        $cid = docker compose ps -q db
        if ($cid) {
            $status = docker inspect --format='{{json .State.Health.Status}}' $cid 2>$null
            if ($status -eq '"healthy"') {
                $healthy = $true
                break
            }
        }
        Start-Sleep -Seconds 1
    }
    if ($healthy) {
        Write-Host "==> Database container is healthy."
    } else {
        Write-Warning "==> Database healthcheck timed out. Attempting to proceed..."
    }
} else {
    Write-Warning "==> Docker not found on PATH. Ensure PostgreSQL 16 + pgvector is running locally or configured via DATABASE_URL."
}

# 3. Start Uvicorn API server or Streamlit dashboard
if ($Dashboard) {
    Write-Host "==> Starting Streamlit dashboard on http://${HostAddress}:${DashboardPort}..."
    python -m streamlit run dashboard/app.py --server.address $HostAddress --server.port $DashboardPort
} else {
    Write-Host "==> Starting Uvicorn API server on http://${HostAddress}:${Port}..."
    python -m uvicorn app.main:app --host $HostAddress --port $Port --reload
}
