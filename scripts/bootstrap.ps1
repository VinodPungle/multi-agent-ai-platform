#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap a fresh clone on Windows.

.DESCRIPTION
    Verifies the toolchain, creates .env, installs Python and frontend
    dependencies, and installs the Git hooks.

    Idempotent: safe to re-run at any time, and the normal way to recover after
    a dependency change.

    PowerShell rather than Python, because it has to run before any Python
    environment exists. `uv` is the one hard prerequisite.

.PARAMETER SkipFrontend
    Install backend dependencies only.

.PARAMETER NoHooks
    Skip Git hook installation.

.EXAMPLE
    .\scripts\bootstrap.ps1

.EXAMPLE
    .\scripts\bootstrap.ps1 -SkipFrontend
#>

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$NoHooks
)

# Stop on the first error. Without this, a failed step scrolls past and the
# script reports success for an environment that is only half built.
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    <#
        Native executables set $LASTEXITCODE rather than throwing, so a failing
        `npm ci` would otherwise be invisible to $ErrorActionPreference.
    #>
    param(
        [Parameter(Mandatory)][string]$Executable,
        [string[]]$Arguments = @()
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

# -----------------------------------------------------------------------------
Write-Step "Checking for uv"
# -----------------------------------------------------------------------------
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    Write-Host @'
uv is not installed, and every other step depends on it.

    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

Then reopen your terminal and run this script again.
'@ -ForegroundColor Red
    exit 1
}
Write-Host (uv --version)

# -----------------------------------------------------------------------------
Write-Step "Verifying the toolchain"
# -----------------------------------------------------------------------------
# `--no-project` skips the workspace sync: the environment is checked before it
# is built, which is the whole point of checking it.
uv run --no-project python scripts/verify_environment.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Environment check failed. Install the tools listed above and re-run." -ForegroundColor Red
    exit 1
}

# -----------------------------------------------------------------------------
Write-Step "Creating .env"
# -----------------------------------------------------------------------------
if (Test-Path .env) {
    Write-Host ".env already exists - left untouched."
}
else {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example. Every default works as-is."
}

# -----------------------------------------------------------------------------
Write-Step "Installing Python dependencies"
# -----------------------------------------------------------------------------
Invoke-Checked uv @('sync', '--all-packages')

# -----------------------------------------------------------------------------
if (-not $SkipFrontend) {
    Write-Step "Installing frontend dependencies"
    # `npm ci` installs the locked tree exactly, as CI does. It also deletes and
    # recreates node_modules, which is what makes re-running this script a
    # reliable repair rather than a partial update.
    Push-Location src/frontend
    try {
        Invoke-Checked npm @('ci', '--no-audit', '--no-fund')
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping frontend dependencies (-SkipFrontend)"
}

# -----------------------------------------------------------------------------
if (-not $NoHooks) {
    Write-Step "Installing Git hooks"
    Invoke-Checked uv @('run', 'pre-commit', 'install', '--install-hooks')
}
else {
    Write-Step "Skipping Git hooks (-NoHooks)"
}

# -----------------------------------------------------------------------------
Write-Step "Done"
# -----------------------------------------------------------------------------
Write-Host @'
Next:

    task dev        backend and frontend with hot reload
    task up         the same stack in Docker Compose
    task check      every gate CI runs

Without Task installed:

    uv run uvicorn agent_platform.api.app:create_app --factory --reload
    cd src/frontend; npm run dev

See docs/developer-setup.md.
'@
