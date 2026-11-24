$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:EARTHSIM_DATA_MODE = 'fixture'
Set-Location "$root/backend"
python -m earthsim.cli doctor
python -m earthsim.cli fixtures install
python -m earthsim.cli fixtures verify
python -m pytest -q
Set-Location "$root/apps/web"
npm run build
npm test -- --run
Set-Location $root
python scripts/bench_api.py
Write-Host 'VERIFY_OK'
