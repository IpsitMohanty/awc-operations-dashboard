$workspace = "D:\AWC_Operational_Efficiency Reports"
$python = "C:\Python314\python.exe"
$streamlitLauncher = Join-Path $workspace "start_awc_dashboard_streamlit.ps1"

Set-Location $workspace

Write-Host ""
Write-Host "[1/4] Running schema transition check..."
& $python .\schema_transition_check.py --folder $workspace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "[2/4] Harmonizing monthly CSV files..."
& $python .\harmonize_merge_awc.py --folder $workspace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "[3/4] Computing anomaly flags, risk snapshots, and alerts..."
& $python .\anomaly_risk_flags.py --folder $workspace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "[4/4] Loading SQLite warehouse..."
& $python .\load_awc_warehouse.py --folder $workspace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Refresh complete."
Write-Host "Starting Streamlit dashboard..."
& powershell -ExecutionPolicy Bypass -File $streamlitLauncher
