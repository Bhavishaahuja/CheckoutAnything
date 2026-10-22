# Leash

AI shopping agents are starting to place real orders, and merchants have no way to know whether the human behind the agent actually wanted that order. Leash is proof of intent for agent orders. The merchant authorizes the PayPal payment but holds the capture while Claude checks the order against the human's mandate. Clean matches capture automatically. Anything off goes to the human with a one-line reason: approve captures, reject voids. If a dispute comes in later, the mandate and the approval are filed as evidence through PayPal's Disputes API. A rubber-stamp watch notices when the human stops really reading approvals and starts asking less often but more pointedly.

**Status: in progress.** Built for the PayPal AI Hackathon.

**Live API:** https://LEASH-API-URL.onrender.com (TODO: fill in after the first Render deploy). Health check at `/health`, docs at `/docs`. It's a free instance, so the first request after 15 idle minutes takes about a minute.

## Local setup (Windows PowerShell)

```powershell
git clone https://github.com/Bhavishaahuja/leash.git
cd leash

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install -r requirements-dev.txt

Copy-Item .env.example .env
# now open .env and fill in your sandbox keys

python check_setup.py
```

### Database

Easiest on Windows: a free Render Postgres, nothing to install. (It expires after 30 days, fine for dev. Both of us can share one.)

1. dashboard.render.com > **New** > **Postgres**.
2. Name it `leash-db`, region **Oregon** (the API runs there too), plan **Free**, then **Create Database**. The free plan allows one database, so we share it.
3. When it's ready, copy the **External Database URL** into `DATABASE_URL` in your `.env`. Paste it as is, the app switches `postgres://` to the psycopg driver.
4. Create the tables:

   ```powershell
   alembic upgrade head
   ```

After changing `backend/app/models.py`, make a migration with `alembic revision --autogenerate -m "what changed"`, read it over, then `alembic upgrade head`.

### Run the API

```powershell
uvicorn backend.app.main:app --reload
```

Then open http://127.0.0.1:8000/health (should say `{"status": "ok"}`) or http://127.0.0.1:8000/docs.

### Check mandate parsing

`POST /mandates` uses Claude to turn the shopper's words into rules. The prompt lives in `backend/app/prompts/mandate.py`. After changing it, run the sample requests (6 real Claude calls, needs `ANTHROPIC_API_KEY`):

```powershell
python backend/scripts/try_mandates.py                              # calls Claude directly, no DB needed
python backend/scripts/try_mandates.py --api http://127.0.0.1:8000  # through the running API
```

Run the checks CI runs:

```powershell
ruff check .
pytest
```

## Deploy (Render)

`render.yaml` is a Render Blueprint for the API: a free Python web service in Oregon that deploys on every push to `main`. The database (`leash-db`) already exists and isn't in the Blueprint; its **Internal Database URL** goes in the service's `DATABASE_URL`.

- Build: `pip install -r requirements.txt` (Python version from `.python-version`)
- Start: `alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`. Migrations run at start because pre-deploy commands are paid-plan only.
- Secrets (`DATABASE_URL`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `ANTHROPIC_API_KEY`) are set in the Render dashboard, never in the file.
- After each merge to `main`, CI waits for `/health` on Render if the repo has a `RENDER_URL` secret.

## Architecture

TODO

## Sandbox logins

TODO

## Demo

TODO: demo video and walkthrough.

### Week 1 end-to-end check

`backend/scripts/week1_e2e.py` runs the whole money flow against a running API: creates a mandate (Claude parses it), places an order with the saved PayPal vault id (authorized with no buyer action) and captures it, places a second one and voids it, then reads both back from PayPal (authorization `CAPTURED` + capture `COMPLETED`, and authorization `VOIDED`).

It needs `spikes/.vault_token.json` (run `python spikes/spike2_vault.py` once) and the PayPal keys in your local `.env` for the read-back.

```powershell
python backend/scripts/week1_e2e.py                                      # local API on :8000
python backend/scripts/week1_e2e.py https://LEASH-API-URL.onrender.com   # Render
```

It's sandbox, so no real money moves. Each run costs one small Claude call.

## Tools used

TODO

## License

MIT, see [LICENSE](LICENSE).
