$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python -m PyInstaller --clean --noconfirm packaging/Inquisitio.spec

$Executable = Join-Path $Root "dist\Inquisitio\Inquisitio.exe"
if (-not (Test-Path $Executable)) { throw "Packaged executable was not created." }

if ($env:WINDOWS_CERTIFICATE_PFX_BASE64 -and $env:WINDOWS_CERTIFICATE_PASSWORD) {
    $Certificate = Join-Path $env:TEMP "inquisitio-signing.pfx"
    [IO.File]::WriteAllBytes($Certificate, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_PFX_BASE64))
    $SignTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $SignTool) { throw "Windows SignTool was not found." }
    & $SignTool.FullName sign /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" /f $Certificate /p $env:WINDOWS_CERTIFICATE_PASSWORD $Executable
    if ($LASTEXITCODE -ne 0) { throw "Windows code signing failed." }
    Remove-Item $Certificate -Force
}

$env:INQUISITIO_DATA_DIR = Join-Path $env:TEMP "inquisitio-build-$([guid]::NewGuid())\cases"
$Process = Start-Process -FilePath $Executable -ArgumentList "--no-browser", "--port", "8876" -PassThru
try {
    $Healthy = $false
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/health" -TimeoutSec 2
            if ($Health.status -eq "ok") { $Healthy = $true; break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $Healthy) { throw "Packaged application did not become healthy." }
} finally {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

$Artifacts = Join-Path $Root "artifacts"
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null
$Archive = Join-Path $Artifacts "Inquisitio-Windows-x64.zip"
Compress-Archive -Path (Join-Path $Root "dist\Inquisitio") -DestinationPath $Archive -Force
Write-Host "Built $Archive"
