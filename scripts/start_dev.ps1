# VIA — Local development environment setup (branch: develop)
#
# Usage:
#   .\scripts\start_dev.ps1                      # reset DB + seed + server
#   .\scripts\start_dev.ps1 -NoServer            # reset DB + seed (sin uvicorn)
#   .\scripts\start_dev.ps1 -GeeKeyFile "C:\otra\ruta\key.json"

param(
    [string]$GeeKeyFile = "C:\Users\Usuario\Documents\Keys\via-tp-3a42e41077c1.json",
    [switch]$NoServer
)

# ── .env (optional overrides — loaded before hardcoded defaults) ──────────────
$envFile = Join-Path (Join-Path $PSScriptRoot "..") ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#\s][^=]*?)\s*=\s*(.*?)\s*$") {
            [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
    Write-Host "      Loaded .env" -ForegroundColor Gray
}

# ── Environment variables ─────────────────────────────────────────────────────
$env:DATABASE_URL         = "postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
$env:JWT_SECRET_KEY       = "dev-only-secret-key-must-be-32chars!"
$env:SEED_ADMIN_EMAIL     = "admin@via.local"
$env:SEED_ADMIN_PASSWORD  = "Admin123456"
$env:VIA_ADMIN_EMAIL      = "admin@via.local"
$env:VIA_ADMIN_PASSWORD   = "Admin123456"
$env:GEE_ENABLED          = "true"
$env:GEE_PROJECT          = "via-tp"
$env:GEE_SERVICE_ACCOUNT  = "via-gee-extractor@via-tp.iam.gserviceaccount.com"
$env:GEE_PRIVATE_KEY_FILE = $GeeKeyFile

# ── Docker DB ─────────────────────────────────────────────────────────────────
Write-Host "`n[1/4] Reiniciando base de datos local..." -ForegroundColor Cyan
docker compose -f docker-compose.postgres.yml down -v
docker compose -f docker-compose.postgres.yml up -d

Write-Host "      Esperando a que Postgres levante (5s)..." -ForegroundColor Gray
Start-Sleep -Seconds 5

# ── Migrations ────────────────────────────────────────────────────────────────
Write-Host "`n[2/4] Ejecutando migraciones..." -ForegroundColor Cyan
python -m alembic upgrade head
if (-not $?) { Write-Host "ERROR: alembic fallo" -ForegroundColor Red; exit 1 }

# ── Seed ──────────────────────────────────────────────────────────────────────
Write-Host "`n[3/4] Cargando datos iniciales..." -ForegroundColor Cyan
python scripts/seed_admin_user.py
python scripts/seed_prod_rulebooks.py

# ── Server ────────────────────────────────────────────────────────────────────
if ($NoServer) {
    Write-Host "`n[OK] Entorno listo. Servidor no iniciado (-NoServer)." -ForegroundColor Green
} else {
    Write-Host "`n[4/4] Iniciando servidor en http://127.0.0.1:8000 ..." -ForegroundColor Cyan
    uvicorn via.main:app --reload --host 127.0.0.1 --port 8000
}
