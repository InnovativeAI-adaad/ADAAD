# DorkHelpers.psm1
# Enhanced PowerShell module for interacting with DORK + Aponi in this Grok session.
# Usage:
#   Import-Module .\DorkHelpers.psm1
#   dork help

$script:AponiBase = "http://localhost:8000"
$script:McpBase   = "http://localhost:8091"

function dork {
    <#
    .SYNOPSIS
    Main DORK + Aponi helper command.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Position=0)]
        [string]$Command = "help",

        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$Args
    )

    switch ($Command.ToLower()) {
        "help" {
            Write-Host "DORK + Aponi Helpers (Aponi on 8000, MCP DORK on 8091)" -ForegroundColor Cyan
            Write-Host "  dork status          -> Show server status and ports"
            Write-Host "  dork ui              -> Open Aponi dashboard in browser"
            Write-Host "  dork health          -> Aponi health check"
            Write-Host "  dork mcp-health      -> DORK MCP health"
            Write-Host "  dork mcp-circuit     -> DORK Circuit Breaker status (dev token)"
            Write-Host "  dork mcp-tools       -> List DORK MCP tools"
            Write-Host "  dork logs            -> Show recent logs from background jobs"
            Write-Host "  dork explore         -> Quick exploration of Aponi/DORK features"
            Write-Host "  dork query <path>    -> Raw query against Aponi (e.g. /api/governance/health)"
            Write-Host "  dork mcp-query <path>-> Raw query against MCP DORK (with dev auth)"
        }
        "status" {
            netstat -ano | findstr ":8000 :8091" | Select-String "LISTENING"
            Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime, CPU | Format-Table -AutoSize
        }
        "ui" {
            Start-Process "$script:AponiBase/"
        }
        "health" {
            try { Invoke-RestMethod "$script:AponiBase/api/health" -TimeoutSec 5 } catch { $_.Exception.Message }
        }
        "mcp-health" {
            try { Invoke-RestMethod "$script:McpBase/health" -TimeoutSec 5 } catch { $_.Exception.Message }
        }
        "mcp-circuit" {
            try {
                $headers = @{ Authorization = "Bearer dev" }
                Invoke-RestMethod "$script:McpBase/circuit/status" -Headers $headers -TimeoutSec 5
            } catch { $_.Exception.Message }
        }
        "mcp-tools" {
            try {
                $headers = @{ Authorization = "Bearer dev" }
                Invoke-RestMethod "$script:McpBase/tools/list" -Headers $headers -TimeoutSec 5
            } catch { $_.Exception.Message }
        }
        "logs" {
            # Try Grok background tasks + PS jobs
            Write-Host "Recent DORK/Aponi activity (from known background tasks):" -ForegroundColor Cyan
            # User can call get_command_or_subagent_output on known task IDs
            Write-Host "Use: get_command_or_subagent_output on the Aponi/MCP task IDs for full logs."
            Receive-Job -Name "*DORK*" -Keep -ErrorAction SilentlyContinue | Select-Object -Last 15
        }
        "explore" {
            Write-Host "Exploring Aponi + DORK features..." -ForegroundColor Cyan
            dork health
            dork mcp-health
            try {
                $gov = Invoke-RestMethod "$script:AponiBase/api/governance/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
                Write-Host "Governance health sample: $($gov | ConvertTo-Json -Compress -Depth 2)"
            } catch {}
            Write-Host "Tip: Open the UI with 'dork ui' for the full visual experience."
        }
        "query" {
            if ($Args.Count -eq 0) { Write-Host "Usage: dork query /some/path"; return }
            $path = $Args[0]
            try { Invoke-RestMethod "$script:AponiBase$path" -TimeoutSec 8 } catch { $_.Exception.Message }
        }
        "mcp-query" {
            if ($Args.Count -eq 0) { Write-Host "Usage: dork mcp-query /some/path"; return }
            $path = $Args[0]
            try {
                $headers = @{ Authorization = "Bearer dev" }
                Invoke-RestMethod "$script:McpBase$path" -Headers $headers -TimeoutSec 8
            } catch { $_.Exception.Message }
        }
        default {
            Write-Host "Unknown command '$Command'. Try 'dork help'."
        }
    }
}

# Convenient aliases
Set-Alias -Name dk -Value dork
Set-Alias -Name dorkui -Value { dork ui }

Export-ModuleMember -Function dork -Alias dk, dorkui

Write-Host "DorkHelpers loaded. Type 'dork help' for commands." -ForegroundColor Green