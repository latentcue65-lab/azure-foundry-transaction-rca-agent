param(
    [ValidateSet('replay', 'foundry')]
    [string]$Mode = 'replay',
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$rcaProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $rcaProjectRoot
try {
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (-not (Test-Path -LiteralPath 'data/transactions.db')) {
        uv run rca seed
        if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed.' }
    }
    Write-Host "Open http://127.0.0.1:$Port. Runtime mode: $Mode."
    uv run rca serve --mode $Mode --with-mock --port $Port
} finally {
    Pop-Location
}
