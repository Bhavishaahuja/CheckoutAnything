# Checkout Anything frontend

React (Vite + TypeScript), Tailwind CSS v4, AG Grid Community, [Magic UI](https://github.com/magicuidesign/magicui) components and [Motion](https://github.com/motiondivision/motion).

## Run it

From the repo root, `dev.cmd` starts the API, this app and the demo stores together. To run only the app:

```cmd
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

`VITE_API_URL` points at the FastAPI backend (default `http://127.0.0.1:8000`). `VITE_LEASH_API_URL` points at the Leash API (default `http://127.0.0.1:8001`).

No backend running? Set `VITE_USE_MOCK=true` in `.env.local`. The UI then plays scripted connect runs for the three demo stores and shows a "Mock data, no backend" badge. Nothing in mock mode talks to PayPal or Claude.

## Screens

| Screen | File | What it shows |
|---|---|---|
| Connect | `src/pages/ConnectPage.tsx` | URL input, the pipeline, the live step log (SSE), and the catalog grid that fills row by row |
| Spec drawer | `src/components/SpecDrawer.tsx` | Click a catalog row: source quote, every check, the spec JSON, version history, extraction notes, a test buy |
| Agent | `src/pages/AgentPage.tsx` | Chat with the shopping agent, tool calls shown inline, receipt when a payment is captured |
| Orders | `src/pages/OrdersPage.tsx` | Intent review (Leash orders next to their mandates, decided in the row) and Purchases (everything bought through a connected store) |

The header has the Replay mode switch and the Reset demo button (inline confirm).

## How the pieces are used

**AG Grid (Community only, no Enterprise features)**

All 20 features and why each is there are in the root README, under [How we use AG Grid](../README.md#how-we-use-ag-grid). The shared pieces are `src/lib/gridTheme.ts`, `src/lib/gridState.ts`, `src/lib/gridFind.tsx`, `src/lib/useGridRows.ts` and `src/components/grid/`.

**Motion + AG Grid** (`src/lib/gridFlash.ts`)
- When an item verifies: AG Grid flashes the row green, and Motion runs a staggered lift across its cells
- When an item fails for good: red flash plus a short shake
- New rows slide in cell by cell
- The check marks draw themselves (SVG path length) and the status pill springs in on every change

**Magic UI** (`src/components/magicui`, copied from the registry, MIT)
- `AnimatedBeam`: the pipeline, the beam follows the current step and runs backwards during a repair
- `BorderBeam`: around the URL bar and the catalog card while a store is connecting
- `ShimmerButton`, `AuroraText`, `AnimatedShinyText`, `DotPattern`, `BlurFade`: the hero
- `NumberTicker`: verified / failed counters and the order tiles
- `AnimatedListItem`: step log entries
- `Confetti`: when the agent's payment is captured
- `AnimatedThemeToggler`: light and dark mode

## API contract

Types for every response live in `src/lib/types.ts` and match `backend/app/main.py`. All calls go through `src/lib/api.ts`.
