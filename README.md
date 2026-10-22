# Leash

AI shopping agents are starting to place real orders, and merchants have no way to know whether the human behind the agent actually wanted that order. Leash is proof of intent for agent orders. The merchant authorizes the PayPal payment but holds the capture while Claude checks the order against the human's mandate. Clean matches capture automatically. Anything off goes to the human with a one-line reason: approve captures, reject voids. If a dispute comes in later, the mandate and the approval are filed as evidence through PayPal's Disputes API. A rubber-stamp watch notices when the human stops really reading approvals and starts asking less often but more pointedly.

**Status: in progress.** Built for the PayPal AI Hackathon.

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
2. Name it `leash-dev`, pick the region closest to you, plan **Free**, then **Create Database**.
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

## Architecture

TODO

## Sandbox logins

TODO

## Demo

TODO

## Tools used

TODO

## License

MIT, see [LICENSE](LICENSE).
