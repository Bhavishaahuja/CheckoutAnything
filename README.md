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
