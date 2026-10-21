$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.build-deps') + ';' + (Join-Path $PSScriptRoot '.automation-deps')
python -m PyInstaller --noconfirm --clean --windowed --name RellenoCliente --collect-all tzdata --collect-all playwright main.py
if ($LASTEXITCODE -ne 0) { throw 'Falló PyInstaller' }
$compiler = Join-Path $PSScriptRoot '.tools\inno\ISCC.exe'
if (-not (Test-Path $compiler)) { $compiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
& $compiler installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Falló Inno Setup' }
