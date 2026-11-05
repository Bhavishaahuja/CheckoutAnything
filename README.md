# Leash

AI shopping agents are starting to place real orders, and merchants have no way to know whether the human behind the agent actually wanted that order. Leash is proof of intent for agent orders. The merchant authorizes the PayPal payment but holds the capture while Claude checks the order against the human's mandate. Clean matches capture automatically. Anything off goes to the human with a one-line reason: approve captures, reject voids. If a dispute comes in later, the mandate and the approval are filed as evidence through PayPal's Disputes API. A rubber-stamp watch notices when the human stops really reading approvals and starts asking less often but more pointedly.

**Status: in progress.** Built for the PayPal AI Hackathon.

**Live API:** https://leash-api-q3rw.onrender.com (sandbox). Health check at [`/health`](https://leash-api-q3rw.onrender.com/health), interactive docs at [`/docs`](https://leash-api-q3rw.onrender.com/docs). It's a free instance, so the first request after 15 idle minutes takes about a minute.

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
- After each merge to `main`, CI waits for `/health` on Render (the repo's `RENDER_URL` secret is set).
- Live at https://leash-api-q3rw.onrender.com. The week 1 end-to-end script passed against it on 2026-10-22: mandate parsed, vault order authorized with no buyer action and captured, second order voided, PayPal confirmed `CAPTURED` / `COMPLETED` / `VOIDED`.

## Architecture

TODO

## Security model

This is a hackathon demo in the PayPal sandbox. The security is real but deliberately small: there are no user accounts.

| Who | Holds | Can do |
|---|---|---|
| Shopping agent | `AGENT_API_KEY` | Create mandates, create and authorize orders. Nothing else |
| Merchant dashboard | `MERCHANT_API_KEY` | Read orders and mandates, create review links |
| Human reviewing an order | One review link | See that one order, approve or reject it once |

What this protects:

- **An agent can't approve its own order.** It can't read a review link or create one, and approving takes a link.
- **Review links are single-use and stored hashed.** Only the SHA-256 of a link's token is saved, so a leaked database can't approve anything. A link dies when its PayPal authorization expires.
- **Attention is measured on the server.** `decision_ms` runs from the first time the link was opened to the tap, so a lying client can't fake attention for the rubber-stamp watch. The client's own number is stored separately and not trusted.
- **Money can't move twice.** A row lock plus a payment claim stops double taps, and capture and void use a derived `PayPal-Request-Id`.
- **Missing config fails closed.** An unset API key means a 401, and any failure in the check sends the order to a human.

What it doesn't protect, and what a production version would change:

- **Real merchant login.** A production version would use real merchant accounts with per-user sessions, not one shared key. Anything shipped in a browser bundle is readable by whoever loads the page, so the dashboard should sit behind a login with the key held on a server.
- **Key rotation.** Rotating a key here means changing an environment variable and redeploying.
- **Who holds a review link.** Anyone with the link can decide that order, so a production version would tie it to the signed-in human.
- **Tokens in URLs.** A review token is in the path, so it can land in access logs and browser history. A production version would exchange it for a session on first open.
- **Link previews.** A chat app that previews a link opens it, which starts the attention clock early and can make a quick tap look considered.
- **Rate limiting.** There is none. A token is 32 random bytes, so guessing isn't practical, but nothing slows down attempts on the API keys.

## Sandbox logins

TODO

## Demo

TODO: demo video and walkthrough.

### Week 1 end-to-end check

`backend/scripts/week1_e2e.py` runs the whole money flow against a running API: creates a mandate (Claude parses it), places an order with the saved PayPal vault id (authorized with no buyer action) that should auto-capture, places a second one that should stop for review, checks the agent key can't approve it, rejects it through a review link, then reads both back from PayPal (authorization `CAPTURED` + capture `COMPLETED`, and authorization `VOIDED`).

It needs `spikes/.vault_token.json` (run `python spikes/spike2_vault.py` once) and the PayPal keys in your local `.env` for the read-back, plus `AGENT_API_KEY` and `MERCHANT_API_KEY` matching the API's.

```powershell
python backend/scripts/week1_e2e.py                                      # local API on :8000
python backend/scripts/week1_e2e.py https://leash-api-q3rw.onrender.com  # Render
```

It's sandbox, so no real money moves. Each run costs one small Claude call.

## Tools used

TODO

## License

MIT, see [LICENSE](LICENSE).
