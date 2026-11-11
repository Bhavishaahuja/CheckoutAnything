# Connect evals

Runs every case through the real Connect pipeline (`connect.run_connect`: real fetcher, live Claude,
the real verifier, the real review flags) and scores the result against hand-written ground truth.
No app code is changed or patched.

- `golden/` one file per case. The three demo stores were written by hand from
  `demo-stores/<slug>/index.html`, never from Claude's output. The four negative cases are
  example.com (live) and the three pages in `fixtures/`.
- `fixtures/` local pages: no prices, a prompt injection that asks for a $1 jacket, and prices
  that only exist in a script or an image. They are served on 127.0.0.1 during the run.
- `run_connect_evals.py` the runner. Read the top of the file for what it does and doesn't touch.
- `test_connect_evals.py` offline checks of the scoring itself (scripted Claude, no PayPal).
- `results/latest.json` and `results/latest.md` the last full run.

Run from the repo root, in cmd (needs `ANTHROPIC_API_KEY`, plus the PayPal sandbox keys for the
default `--paypal sandbox`):

```
.venv\Scripts\python.exe evals\connect\run_connect_evals.py
```

`--runs 1` for a quick pass, `--paypal echo` to skip PayPal entirely, `--cases a b` for a few cases.
The offline checks: `.venv\Scripts\python.exe -m pytest evals\connect -q`.

What "wrong prices verified" counts: a verified item whose base price, a variant price or an add-on
price disagrees with the golden file, an item the page says isn't for sale, an item the page gives no
price for, or an item that isn't on the page at all. It is the Connect number that has to be 0.
