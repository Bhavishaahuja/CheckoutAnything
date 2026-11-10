@echo off
rem One command local setup for Windows cmd. Run it from the repo root:  dev.cmd
rem It installs what's missing, then opens three windows: the API (8000), the app (5173)
rem and the demo stores (5174). Fill in .env first (copy .env.example).

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example. Fill in the PayPal and Anthropic keys, then run dev.cmd again.
  exit /b 1
)

if not exist .venv (
  python -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt -r requirements-dev.txt || exit /b 1
rem the Agent Toolkit pins old framework versions we never import, so skip its dependencies
pip install -q --no-deps paypal-agent-toolkit || exit /b 1

if not exist frontend\node_modules (
  pushd frontend
  call npm ci || exit /b 1
  popd
)

start "Checkout Anything API" cmd /k ".venv\Scripts\activate.bat && uvicorn backend.app.main:app_factory --factory --port 8000"
start "Checkout Anything app" cmd /k "cd frontend && npm run dev"
start "Demo stores" cmd /k ".venv\Scripts\activate.bat && python -m http.server 5174 --directory demo-stores"

echo.
echo API:          http://127.0.0.1:8000/health
echo App:          http://localhost:5173
echo Demo stores:  http://localhost:5174
