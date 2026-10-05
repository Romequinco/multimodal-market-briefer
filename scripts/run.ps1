# Arranque en Windows (PowerShell): crea .venv, instala dependencias, prepara .env y lanza la app.
# Nota: fichero solo ASCII a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\run.ps1  [-Local]   (-Local instala modelos locales)
param([switch]$Local)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "Creando entorno virtual en .venv ..."
    python -m venv $Venv
    if (-not $?) { throw "No se pudo crear el entorno virtual (Python 3.11+ instalado y en el PATH?)" }
}

Write-Host "Instalando dependencias ..."
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r requirements.txt
if ($Local) { & $Py -m pip install -r requirements-local.txt }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creado .env a partir de .env.example: rellena tus claves (sin claves se usan mocks)."
}

$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "Lanzando Market Briefer en http://localhost:8501 ..."
& $Py -m streamlit run app/main.py
