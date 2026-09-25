# Agentic RAG 电商智能客服 - 一键启动（UTF-8 / PowerShell 版本）
# 用法：
#   .\start.ps1          # 启动后端 + 前端（需要 .env、MySQL、本地模型）
#   .\start.ps1 -Lite    # Lite 演示：SQLite + BM25 + Mock LLM，无需任何外部依赖
#   .\stop.ps1           # 停止后台服务
param(
    [switch]$Lite
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
chcp 65001 > $null

function Fail([string]$Message) {
    Write-Host "[错误] $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "未检测到 python，请安装 Python 3.12+ 并加入 PATH。"
}

if ($Lite) {
    Write-Host "=== Lite 模式：SQLite + BM25 + Mock LLM（无需 .env / MySQL / GPU / API Key） ===" -ForegroundColor Cyan
    Set-Location (Join-Path $Root "backend")
    python scripts/demo.py
    exit $LASTEXITCODE
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Fail "未找到 .env。请复制 .env.example 为 .env 并填写配置；或运行 .\start.ps1 -Lite 体验离线演示。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "未检测到 npm，请安装 Node.js 20+ 并加入 PATH。"
}

Write-Host "[1/2] 启动后端 FastAPI（端口 8000）..." -ForegroundColor Green
$backend = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    "-NoExit", "-Command",
    "chcp 65001 > `$null; Set-Location '$Root\backend'; python -m uvicorn app.main:app --port 8000"
)

Write-Host "[2/2] 启动前端 Vite（端口 5173）..." -ForegroundColor Green
$frontend = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList @(
    "-NoExit", "-Command",
    "chcp 65001 > `$null; Set-Location '$Root\frontend'; npm run dev"
)

$runDir = Join-Path $Root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
@($backend.Id, $frontend.Id) | Set-Content -Path (Join-Path $runDir "pids.txt") -Encoding ascii

Write-Host ""
Write-Host "服务已启动："
Write-Host "  前端页面      http://localhost:5173"
Write-Host "  健康检查      http://127.0.0.1:8000/api/v1/health"
Write-Host "  接口文档      http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "提示：首次启动需预热 BGE-M3 / Reranker 约 20~30 秒，health 返回 model_ready: true 后可用。"
Write-Host "      管理员账号 admin / 123456（演示密码，请尽快修改）。"
Write-Host "      停止服务：.\stop.ps1"