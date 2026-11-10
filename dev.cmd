@echo off
rem One command local setup for Windows cmd. Run it from the repo root:  dev.cmd
rem It installs what's missing, then opens five windows: the API (8000), the app (5173),
rem the demo stores (5174), the Check API (8001) and the Check app (5175). Fill in .env first
rem (copy .env.example).
rem The Check service reads its own check\.env and needs a Postgres to talk to (see check\.env.example).

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

rem the Check service's requirements are ours plus alembic, so it shares the venv
pip install -q -r check\requirements.txt || exit /b 1

if not exist frontend\node_modules (
  pushd frontend
  call npm ci || exit /b 1
  popd
)

start "Checkout Anything API" cmd /k ".venv\Scripts\activate.bat && uvicorn backend.app.main:app_factory --factory --port 8000"
start "Checkout Anything app" cmd /k "cd frontend && npm run dev"
start "Demo stores" cmd /k ".venv\Scripts\activate.bat && python -m http.server 5174 --directory demo-stores"

rem The Check service runs from check\ so that backend.app is its package and .env is its own file
set CHECK_STARTED=0
if exist check\.env (
  start "Check API" cmd /k "cd check && ..\.venv\Scripts\activate.bat && alembic upgrade head && uvicorn backend.app.main:app --port 8001"
  rem the Check app: the dashboard, and the confirm page the Orders grid shows in its review drawer.
  rem its own port, since the main app has 5173
  call :start_check_app || exit /b 1
  set CHECK_STARTED=1
) else (
  copy check\.env.example check\.env >nul
  echo Created check\.env from check\.env.example. Fill it in and run dev.cmd again to start the Check API.
)

echo.
echo API:          http://127.0.0.1:8000/health
echo App:          http://localhost:5173
echo Demo stores:  http://localhost:5174
if "%CHECK_STARTED%"=="1" echo Check API:    http://127.0.0.1:8001/health
if "%CHECK_STARTED%"=="1" echo Check app:    http://localhost:5175
if "%CHECK_STARTED%"=="1" echo For the two apps to work together: CHECK_FRONTEND_URL=http://localhost:5175 in .env,
if "%CHECK_STARTED%"=="1" echo and http://localhost:5175 in FRONTEND_ORIGINS in check\.env
exit /b 0

rem ---- the Check app. a subroutine so its ifs stay out of the block above ----
:start_check_app
if not exist check\frontend\node_modules (
  pushd check\frontend
  call npm ci || exit /b 1
  popd
)
rem first run only: point it at the local Check API and at the main app. yours to edit after that
if not exist check\frontend\.env.local (
  >check\frontend\.env.local echo VITE_API_URL=http://127.0.0.1:8001
  >>check\frontend\.env.local echo VITE_USE_MOCKS=false
  >>check\frontend\.env.local echo VITE_CONNECT_URL=http://localhost:5173
  >>check\frontend\.env.local echo VITE_CHECK_URL=http://localhost:5175
)
start "Check app" cmd /k "cd check\frontend && npm run dev -- --port 5175 --strictPort"
exit /b 0
