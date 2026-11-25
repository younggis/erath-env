$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root/backend"
python -m earthsim.cli doctor
python -m pytest -q
Set-Location "$root/apps/web"
npm run build
npm test -- --run
Set-Location $root
Write-Host 'VERIFY_OK'
