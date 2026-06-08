<#
.SYNOPSIS
    Starts DORK (the ADAAD intelligence layer) in this PowerShell / Grok environment.

.DESCRIPTION
    Handles Windows-specific issues (fcntl shims, env vars) and launches either:
      - The full server (whaledic + DORK APIs)
      - The lighter MCP/DORK intelligence server (recommended for Grok sessions)

.USAGE
    .\Start-Dork.ps1                 # Starts MCP server (lightweight, good for Grok)
    .\Start-Dork.ps1 -FullServer     # Starts the big FastAPI server on :8000
    .\Start-Dork.ps1 -Background     # Starts in background job

.EXAMPLE
    .\Start-Dork.ps1
    # Then in Grok you can interact with DORK via the MCP tools or direct HTTP
#>

param(
    [switch]$FullServer,
    [switch]$Background,
    [int]$Port = 8091
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "=== Starting DORK in PowerShell Grok environment ===" -ForegroundColor Cyan

# 1. Add shims so fcntl etc. don't explode on Windows
$env:PYTHONPATH = "$root\shims;$env:PYTHONPATH"

# 2. Required secrets for DORK/MCP
$env:ADAAD_MCP_JWT_SECRET = "devlocal2026"

if ($FullServer) {
    Write-Host "Launching FULL DORK + whaledic server (FastAPI on :8000)..." -ForegroundColor Yellow
    $cmd = "python server.py"
} else {
    Write-Host "Launching DORK MCP intelligence server (recommended for this Grok session)..." -ForegroundColor Green
    Write-Host "  Listening on port $Port" -ForegroundColor DarkGray
    $cmd = "python runtime/mcp/server.py --port $Port"
}

if ($Background) {
    Write-Host "Starting in background PowerShell job..." -ForegroundColor Magenta
    $job = Start-Job -ScriptBlock {
        param($root, $cmd, $envPythonPath, $jwt)
        $env:PYTHONPATH = $envPythonPath
        $env:ADAAD_MCP_JWT_SECRET = $jwt
        Set-Location $root
        Invoke-Expression $cmd
    } -ArgumentList $root, $cmd, $env:PYTHONPATH, $env:ADAAD_MCP_JWT_SECRET

    Write-Host "DORK started as background job ID $($job.Id)" -ForegroundColor Green
    Write-Host "Use 'Receive-Job -Id $($job.Id) -Keep' to see output." -ForegroundColor DarkGray
    Write-Host "Use 'Stop-Job -Id $($job.Id)' to stop it." -ForegroundColor DarkGray
} else {
    Write-Host "Running in foreground. Press Ctrl+C to stop." -ForegroundColor Yellow
    Invoke-Expression $cmd
}