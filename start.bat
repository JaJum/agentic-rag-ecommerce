@echo off
title LangChain RAG 启动器
cd /d "%~dp0"

echo ============================================
echo   LangChain RAG 知识库问答系统 · 一键启动
echo ============================================

if not exist ".env" goto noenv
where python >nul 2>nul
if errorlevel 1 goto nopy
where npm >nul 2>nul
if errorlevel 1 goto nonpm

echo [1/2] 启动后端 FastAPI（端口 8000）...
cd /d "%~dp0backend"
start "RAG-Backend" cmd /k "python -m uvicorn app.main:app --port 8000"

echo [2/2] 启动前端 Vite（端口 5173）...
cd /d "%~dp0frontend"
start "RAG-Frontend" cmd /k "npm run dev"

echo.
echo 两个服务窗口已打开：
echo   前端页面      http://localhost:5173
echo   后端健康检查  http://127.0.0.1:8000/api/v1/health
echo   接口文档      http://127.0.0.1:8000/docs
echo.
echo 提示：后端需预热 BGE-M3 / Reranker 模型约 20~30 秒，
echo       health 返回 model_ready: true 后即可使用。
echo       管理员账号 admin / 123456。
echo       停止服务：关闭两个服务窗口即可。
pause
exit /b 0

:noenv
echo [错误] 未找到 .env，请先复制 .env.example 为 .env 并填写配置。
pause
exit /b 1

:nopy
echo [错误] 未检测到 python，请安装 Python 3.12+ 并加入 PATH。
pause
exit /b 1

:nonpm
echo [错误] 未检测到 npm，请安装 Node.js 24+ 并加入 PATH。
pause
exit /b 1
