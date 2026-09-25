# 停止 start.ps1 启动的后端/前端进程树
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $Root ".run\pids.txt"
if (-not (Test-Path $pidFile)) {
    Write-Host "没有找到 .run\pids.txt，服务可能未通过 start.ps1 启动。" -ForegroundColor Yellow
    exit 0
}
foreach ($procId in (Get-Content $pidFile)) {
    if ($procId -match "^\d+$") {
        taskkill /PID $procId /T /F > $null 2>&1
    }
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "已停止 start.ps1 启动的服务。" -ForegroundColor Green