# Fixtures for replay mode

One JSON file per demo store, recorded from a real run (real page fetch, real Claude answers).
Replay mode reads these instead of fetching the page and calling Claude. PayPal sandbox calls
still run live.

They are recorded, never written by hand:

```
set RECORD_FIXTURES=1
uvicorn backend.app.main:app_factory --factory --port 8000
python backend/scripts/record_fixtures.py
```

A store with no fixture here fails with a clear error in replay mode.
