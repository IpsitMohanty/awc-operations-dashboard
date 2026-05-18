$workspace = "D:\AWC_Operational_Efficiency Reports"
$python = "C:\Python314\python.exe"
$hostName = "127.0.0.1"
$port = 8501
$appScript = Join-Path $workspace "awc_dashboard_streamlit.py"

Set-Location $workspace

$existingListener = Get-NetTCPConnection -LocalAddress $hostName -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existingListener) {
    try {
        Stop-Process -Id $existingListener.OwningProcess -ErrorAction Stop
        Start-Sleep -Milliseconds 500
    }
    catch {
    }
}

Write-Host "Starting Streamlit dashboard at http://$hostName`:$port"
Write-Host "Keep this PowerShell window open while using the dashboard."
& $python -m streamlit run $appScript --server.address $hostName --server.port $port
