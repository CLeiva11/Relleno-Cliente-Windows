$ErrorActionPreference = 'Stop'
$managedCredentials = Join-Path $PSScriptRoot 'relleno\_managed_hikcentral.py'
$passwords = @($env:RELLENO_HIKCENTRAL_PASSWORDS -split '\|' | Where-Object { $_ })
if ($passwords.Count -lt 1) {
    throw 'Defina RELLENO_HIKCENTRAL_PASSWORDS con las claves separadas por | antes de compilar.'
}
$literal = ($passwords | ForEach-Object { "'" + ($_ -replace "'", "\\'") + "'" }) -join ', '
Set-Content -Path $managedCredentials -Encoding UTF8 -Value "PASSWORDS = ($literal,)"
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.build-deps') + ';' + (Join-Path $PSScriptRoot '.automation-deps')
try {
    python -m PyInstaller --noconfirm --clean --windowed --name RellenoCliente --collect-all tzdata --collect-all playwright main.py
    if ($LASTEXITCODE -ne 0) { throw 'Falló PyInstaller' }
    $compiler = Join-Path $PSScriptRoot '.tools\inno\ISCC.exe'
    if (-not (Test-Path $compiler)) { $compiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
    & $compiler installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Falló Inno Setup' }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $managedCredentials
}
