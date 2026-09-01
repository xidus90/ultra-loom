#!/usr/bin/env pwsh
# UltraLoom Native Binary & Shim Installer for Windows / PowerShell

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "==> Installing UltraLoom native binaries..." -ForegroundColor Cyan

# 1. Resolve target bin directory
$goBin = $(go env GOBIN)
if ([string]::IsNullOrWhiteSpace($goBin)) {
    $goPath = $(go env GOPATH)
    if (-not [string]::IsNullOrWhiteSpace($goPath)) {
        $goBin = Join-Path $goPath "bin"
    } else {
        $goBin = Join-Path $env:USERPROFILE "go\bin"
    }
}

if (-not (Test-Path -Path $goBin)) {
    New-Item -ItemType Directory -Force -Path $goBin | Out-Null
}

Write-Host "Target directory: $goBin" -ForegroundColor Gray

# 2. Build Go binaries
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Building ulguard.exe..." -ForegroundColor Gray
go build -o (Join-Path $goBin "ulguard.exe") (Join-Path $root "cmd\guard")

Write-Host "Building ulinit.exe..." -ForegroundColor Gray
go build -o (Join-Path $goBin "ulinit.exe") (Join-Path $root "cmd\init")

# 3. Create POSIX bash shims for Git Bash & WSL compatibility
$tools = @("ulguard", "ulinit")
foreach ($tool in $tools) {
    $shimPath = Join-Path $goBin $tool
    $shimContent = @"
#!/usr/bin/env bash
exec ${tool}.exe "`$@"
"@
    [System.IO.File]::WriteAllText($shimPath, $shimContent.Replace("`r`n", "`n"))
    Write-Host "Created Bash shim: $shimPath" -ForegroundColor Gray
}

# 4. Verify PATH configuration
$pathParts = $env:PATH -split ';'
$targetResolved = $goBin.TrimEnd('\')
$inPath = $false
foreach ($part in $pathParts) {
    if ([string]::IsNullOrWhiteSpace($part)) { continue }
    $resolved = Resolve-Path -Path $part -ErrorAction SilentlyContinue
    if ($null -ne $resolved -and $resolved.Path.TrimEnd('\') -eq $targetResolved) {
        $inPath = $true
        break
    }
}

if ($inPath) {
    Write-Host "`n[OK] UltraLoom binaries (ulguard, ulinit) successfully installed to $goBin (on PATH)." -ForegroundColor Green
} else {
    Write-Host "`n[WARNING] $goBin is not on your PATH. Please add it to your system PATH environment variable." -ForegroundColor Yellow
}
