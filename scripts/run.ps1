# Arranque en Windows (PowerShell): crea .venv, instala dependencias, prepara .env y lanza la app.
# Nota: fichero solo ASCII a proposito (PowerShell 5.1 lee los .ps1 sin BOM como ANSI).
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\run.ps1 [-Local] [-Expose] [-Port 8501] [-Reinstall]
#   -Local      instala tambien los modelos locales (requirements-local.txt, varios GB)
#   -Expose     escucha en todas las interfaces (0.0.0.0): visible desde otros equipos de la red.
#               Por defecto solo localhost, para no exponer tus claves de API en la red de clase.
#   -Port       puerto de Streamlit (8501 por defecto)
#   -Reinstall  fuerza pip install aunque los requirements no hayan cambiado
param(
    [switch]$Local,
    [switch]$Expose,
    [int]$Port = 8501,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail([string]$Msg) {
    Write-Host ""
    Write-Host "ERROR: $Msg" -ForegroundColor Red
    exit 1
}

# Devuelve $true si el ejecutable (con sus argumentos previos, p. ej. "-3.11") es Python >= 3.11.
function Test-Py311([string]$Exe, [string[]]$PreArgs = @()) {
    try {
        $out = & $Exe @PreArgs -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "1")
    } catch {
        return $false
    }
}

$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

# Un .venv creado con un Python antiguo no sirve: se avisa en vez de seguir con errores raros.
if ((Test-Path $Py) -and -not (Test-Py311 $Py)) {
    Fail "El entorno .venv usa un Python anterior a 3.11. Borra la carpeta .venv y vuelve a ejecutar."
}

if (-not (Test-Path $Py)) {
    # Candidatos: el lanzador py (habitual en Windows) y python del PATH.
    $candidates = @("py -3.11", "py -3", "python", "python3")
    $SysExe = $null
    $SysArgs = @()
    foreach ($c in $candidates) {
        $parts = @($c -split ' ')
        $cArgs = @()
        if ($parts.Count -gt 1) { $cArgs = @($parts[1..($parts.Count - 1)]) }
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        if (Test-Py311 $parts[0] $cArgs) { $SysExe = $parts[0]; $SysArgs = $cArgs; break }
    }
    if ($null -eq $SysExe) {
        Fail ("No encuentro Python 3.11 o superior. Instalalo desde https://www.python.org/downloads/ " +
              "(o 'winget install Python.Python.3.11') y vuelve a ejecutar.")
    }
    Write-Host "Creando entorno virtual en .venv con: $SysExe $($SysArgs -join ' ') ..."
    & $SysExe @SysArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Py)) { Fail "No se pudo crear el entorno virtual .venv." }
}

# Instala solo si cambian los requirements (asi se puede relanzar sin red el dia de la demo).
$reqFiles = @("requirements.txt")
if ($Local) { $reqFiles += "requirements-local.txt" }
$hash = ($reqFiles | ForEach-Object { (Get-FileHash $_ -Algorithm SHA256).Hash }) -join "-"
$stamp = Join-Path $Venv ".deps-installed"
$installed = ""
if (Test-Path $stamp) { $installed = (Get-Content $stamp -Raw).Trim() }

if ($Reinstall -or $installed -ne $hash) {
    Write-Host "Instalando dependencias (la primera vez tarda unos minutos) ..."
    & $Py -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Fallo al actualizar pip (hay conexion a Internet?)." }
    & $Py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "Fallo 'pip install -r requirements.txt'. Revisa el mensaje de arriba." }
    if ($Local) {
        & $Py -m pip install -r requirements-local.txt
        if ($LASTEXITCODE -ne 0) { Fail "Fallo 'pip install -r requirements-local.txt'." }
    }
    Set-Content -Path $stamp -Value $hash -Encoding ASCII
} else {
    Write-Host "Dependencias ya instaladas (usa -Reinstall para forzar)."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creado .env a partir de .env.example."
    Write-Host "  Sin claves de API la app funciona igual en modo demo (datos de ejemplo y mocks)."
    Write-Host "  Para el modo real, rellena ANTHROPIC_API_KEY (y las demas que uses) en .env."
}

$env:PYTHONPATH = Join-Path $Root "src"
if ($Expose) {
    $Address = "0.0.0.0"
    Write-Host "AVISO: -Expose activo. Cualquiera en tu red podra usar la app (y tus claves de API)." -ForegroundColor Yellow
} else {
    $Address = "localhost"
}
Write-Host "Lanzando Briefly en http://localhost:$Port  (Ctrl+C para parar) ..."
& $Py -m streamlit run app/main.py --server.address $Address --server.port $Port --server.headless true
exit $LASTEXITCODE
