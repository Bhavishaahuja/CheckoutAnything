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

`VITE_API_URL` points at the FastAPI backend (default `http://127.0.0.1:8000`).

`VITE_CHECK_URL` is where the Check app (`check/frontend`) is served (default `http://localhost:5175`). Both apps wear the same header (`src/components/AppHeader.tsx` and `app-header.css`, kept identical in both, CI compares them): Connect and Orders are screens here, Check opens the Check app, and Disputes is a screen here when the API can reach Check. The Check app links back with `VITE_CONNECT_URL`.

No backend running? Set `VITE_USE_MOCK=true` in `.env.local`. The UI then plays scripted connect runs for the three demo stores and shows a "Mock data, no backend" badge. Nothing in mock mode talks to PayPal or Claude.

## Screens

| Screen | File | What it shows |
|---|---|---|
| Connect | `src/pages/ConnectPage.tsx` | URL input, the pipeline, the live step log (SSE), and the catalog grid that fills row by row |
| Spec drawer | `src/components/SpecDrawer.tsx` | Click a catalog row: source quote, every check, the spec JSON, version history, extraction notes, a test buy |
| Agent | `src/pages/AgentPage.tsx` | Chat with the shopping agent, tool calls shown inline, receipt when a payment is captured |
| Orders | `src/pages/OrdersPage.tsx` | All orders, polled every 3 seconds. Orders on hold are pinned on top, and Review opens the confirm page in a drawer |

The header has the Replay mode switch and the Reset demo button (inline confirm).

## How the pieces are used

**AG Grid (Community only, no Enterprise features)**

All 20 features and why each is there are in the root README, under [How we use AG Grid](../README.md#how-we-use-ag-grid). The shared pieces are `src/lib/gridTheme.ts`, `src/lib/gridState.ts`, `src/lib/gridFind.tsx`, `src/lib/useGridRows.ts` and `src/components/grid/`.

**Motion in the grids' own UI** (`src/components/grid/motion.tsx`)
- Counters roll when they change: fields that need a look, rows to publish, find position, pinned orders, fast approvals
- The amber counter turns into a green check with a bounce at 0, and a blocked publish shakes its reason
- Status chips, flag marks and the Fast approval chip spring in, and the rubber-stamp strip jolts when another fast approval lands
- Tooltips, the price editor, the columns menu and the overlays scale and rise in. The loading bar springs between steps
- `MotionConfig reducedMotion="user"` in `main.tsx` turns movement off for anyone whose system asks for less

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
