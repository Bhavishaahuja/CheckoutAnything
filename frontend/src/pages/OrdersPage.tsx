// Screen 4: every purchase made through connected stores, live.

import type { ColDef, GetRowIdParams } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import { Bot, Check, Hand, Hourglass, Search, ShieldCheck, ShieldQuestion, Undo2, X } from "lucide-react"
import { AnimatePresence } from "motion/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { Card, CopyId, ErrorNote, Pill, Switch } from "@/components/bits"
import { ReviewDrawer } from "@/components/ReviewDrawer"
import { NumberTicker } from "@/components/magicui/number-ticker"
import { api } from "@/lib/api"
import { clockTime, decisionTime, money } from "@/lib/format"
import { flashGridRow } from "@/lib/gridFlash"
import { calmTheme } from "@/lib/gridTheme"
import type { Order } from "@/lib/types"
import { useGridRows } from "@/lib/useGridRows"

const POLL_MS = 3000

interface OrderRow extends Order {
  seen_at: number
}

// the grid starts empty (never "loading"), rows then arrive as transactions
const NO_ROWS: OrderRow[] = []

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card className="px-4 py-3.5">
      <div className="text-2xl font-semibold tabular-nums">{children}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </Card>
  )
}

function Ticker({ value, decimals = 0 }: { value: number; decimals?: number }) {
  if (value === 0) return <span>{decimals ? "0.00" : "0"}</span>
  return <NumberTicker value={value} decimalPlaces={decimals} />
}

function ByCell({ value }: CustomCellRendererProps<OrderRow>) {
  if (value === "agent") {
    return (
      <Pill tone="info">
        <Bot className="size-3.5" /> Agent
      </Pill>
    )
  }
  return (
    <Pill tone="muted">
      <Hand className="size-3.5" /> Manual
    </Pill>
  )
}

function StatusCell({ data }: CustomCellRendererProps<OrderRow>) {
  if (!data) return null
  if (data.status === "captured") {
    return (
      <Pill tone="ok">
        <Check className="size-3.5" strokeWidth={3} /> Captured
      </Pill>
    )
  }
  // the two states only an order that went through Check can be in
  if (data.status === "authorized" && !data.error) {
    return (
      <Pill tone="warn">
        <Hourglass className="size-3.5" /> On hold
      </Pill>
    )
  }
  if (data.status === "voided") {
    return (
      <Pill tone="muted">
        <Undo2 className="size-3.5" /> Voided
      </Pill>
    )
  }
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Pill tone="bad">
        <X className="size-3.5" strokeWidth={3} /> {data.status}
      </Pill>
      {data.error && (
        <span className="truncate text-xs text-muted-foreground" title={data.error}>
          {data.error}
        </span>
      )}
    </span>
  )
}

// what Check concluded about the order, or a dash for an order that never went through it
function VerdictCell({ data }: CustomCellRendererProps<OrderRow>) {
  if (!data || data.check_order_id === null) return <span className="text-muted-foreground/60">-</span>
  if (data.check_verdict === "match") {
    return (
      <Pill tone="ok">
        <ShieldCheck className="size-3.5" /> Match
      </Pill>
    )
  }
  if (data.check_verdict === "mismatch") {
    return (
      <Pill tone="bad">
        <X className="size-3.5" strokeWidth={3} /> Mismatch
      </Pill>
    )
  }
  if (data.check_verdict === "unsure") {
    return (
      <Pill tone="warn">
        <ShieldQuestion className="size-3.5" /> Unsure
      </Pill>
    )
  }
  return <span className="text-xs text-muted-foreground">Not checked</span>
}

const REVIEW_LABELS: Record<string, string> = {
  auto_approved: "Auto-captured",
  approved: "Approved",
  rejected: "Rejected",
}

function ReviewCell({ data, context }: CustomCellRendererProps<OrderRow, unknown, GridContext>) {
  if (!data || !data.review_state) return <span className="text-muted-foreground/60">-</span>
  if (data.review_state !== "needs_review") {
    const tone = data.review_state === "rejected" ? "muted" : "ok"
    return <Pill tone={tone}>{REVIEW_LABELS[data.review_state] || data.review_state}</Pill>
  }
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Pill tone="warn">Needs review</Pill>
      {context.reviewLinks && (
        // opens the drawer. it never decides anything from here, the confirm page does.
        // 44px tall so it's a fair target on a touch screen
        <button
          type="button"
          onClick={() => context.openReview(data.id)}
          aria-label={"Review order " + data.id}
          className="inline-flex h-11 items-center rounded-lg bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:opacity-90"
        >
          Review
        </button>
      )}
    </span>
  )
}

interface GridContext {
  reviewLinks: boolean
  openReview: (orderId: number) => void
}

export function OrdersPage({
  active,
  refreshKey,
  checkOn,
  reviewLinks,
}: {
  active: boolean
  refreshKey: number
  // agent orders go through Check, so the grid shows what it decided
  checkOn: boolean
  reviewLinks: boolean
}) {
  // the order whose review drawer is open
  const [reviewId, setReviewId] = useState<number | null>(null)
  // bumped to load right away instead of waiting for the next poll
  const [nudge, setNudge] = useState(0)
  const [rows, setRows] = useState<OrderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [grouped, setGrouped] = useState(true)
  const [search, setSearch] = useState("")
  const firstLoad = useRef(true)

  useEffect(() => {
    if (!active) return
    let cancelled = false

    const load = async () => {
      if (document.hidden) return
      try {
        const orders = await api.listOrders()
        if (cancelled) return
        setError(null)
        setRows((previous) => {
          const before = new Map(previous.map((row) => [row.id, row]))
          let changed = orders.length !== previous.length
          const next = orders.map((order) => {
            const old = before.get(order.id)
            if (
              old &&
              old.status === order.status &&
              old.capture_id === order.capture_id &&
              old.review_state === order.review_state &&
              old.check_verdict === order.check_verdict &&
              old.decision_ms === order.decision_ms
            )
              return old
            changed = true
            // orders already there on first load don't flash, new ones do
            return { ...order, seen_at: firstLoad.current ? 0 : Date.now() }
          })
          firstLoad.current = false
          return changed ? next : previous
        })
      } catch (problem) {
        if (!cancelled) setError(problem instanceof Error ? problem.message : "Couldn't load orders")
      }
    }

    void load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [active, refreshKey, nudge])

  const { gridApi, onGridReady } = useGridRows(rows, (row) => String(row.id))

  const wrapper = useRef<HTMLDivElement>(null)
  const flashed = useRef<Set<number>>(new Set())

  // a new order lights up its row: AG Grid flash plus a Motion slide-in
  useEffect(() => {
    if (!gridApi) return
    for (const row of rows) {
      if (flashed.current.has(row.id)) continue
      flashed.current.add(row.id)
      if (row.seen_at === 0 || Date.now() - row.seen_at > 1500) continue
      flashGridRow(gridApi, wrapper.current, String(row.id), row.status === "captured" ? "ok" : "bad")
    }
  }, [gridApi, rows])

  useEffect(() => {
    if (gridApi && !gridApi.isDestroyed()) gridApi.setGridOption("quickFilterText", search)
  }, [gridApi, search])

  const columnDefs = useMemo<ColDef<OrderRow>[]>(
    () => [
      {
        headerName: "Store",
        colId: "store",
        valueGetter: (params) => params.data?.store_name || "Store " + params.data?.store_id,
        // one tall cell per store when grouping is on (cell spanning, a Community feature)
        spanRows: grouped,
        sort: grouped ? "asc" : null,
        sortIndex: 0,
        cellClass: grouped ? "font-medium !items-start !pt-3 bg-card" : "font-medium",
        flex: 1.2,
        minWidth: 170,
      },
      { headerName: "Item", field: "description", flex: 2, minWidth: 200 },
      { headerName: "Qty", field: "quantity", width: 72, type: "rightAligned", cellClass: "tabular-nums" },
      {
        headerName: "Total",
        field: "total",
        width: 104,
        type: "rightAligned",
        cellClass: "font-mono tabular-nums",
        valueFormatter: (params) => (params.data ? money(params.value, params.data.currency) : ""),
        comparator: (a, b) => Number(a) - Number(b),
      },
      {
        headerName: "PayPal order",
        field: "paypal_order_id",
        width: 180,
        cellRenderer: (params: CustomCellRendererProps<OrderRow>) => <CopyId value={params.value} />,
      },
      {
        headerName: "Capture",
        field: "capture_id",
        width: 180,
        cellRenderer: (params: CustomCellRendererProps<OrderRow>) => <CopyId value={params.value} />,
      },
      { headerName: "Bought by", field: "created_by", width: 122, cellRenderer: ByCell },
      { headerName: "Status", field: "status", cellRenderer: StatusCell, flex: 1, minWidth: 130 },
      // the Check columns, only when agent orders go through Check
      { headerName: "Check", field: "check_verdict", cellRenderer: VerdictCell, width: 124, hide: !checkOn },
      {
        headerName: "Reason",
        field: "check_reason",
        flex: 2,
        minWidth: 220,
        hide: !checkOn,
        tooltipField: "check_reason",
        cellClass: "text-muted-foreground",
      },
      { headerName: "Review", field: "review_state", cellRenderer: ReviewCell, width: 236, hide: !checkOn },
      {
        headerName: "Time to decide",
        field: "decision_ms",
        width: 132,
        type: "rightAligned",
        hide: !checkOn,
        cellClass: "tabular-nums",
        valueFormatter: (params) => decisionTime(params.value),
      },
      {
        headerName: "Time",
        field: "created_at",
        width: 118,
        sort: "desc",
        sortIndex: 1,
        valueFormatter: (params) => clockTime(params.value),
        cellClass: "text-muted-foreground tabular-nums",
      },
    ],
    [grouped, checkOn]
  )

  const openReview = useCallback((orderId: number) => setReviewId(orderId), [])
  const closeReview = useCallback(() => setReviewId(null), [])
  // the confirm page in the drawer finished a decision: read the row again now
  const reviewDecided = useCallback(() => setNudge((count) => count + 1), [])

  const gridContext = useMemo<GridContext>(() => ({ reviewLinks, openReview }), [reviewLinks, openReview])

  const reviewOrder = reviewId === null ? null : rows.find((row) => row.id === reviewId) || null

  let captured = 0
  let volume = 0
  let byAgent = 0
  let waiting = 0
  const storeIds = new Set<number>()
  for (const row of rows) {
    storeIds.add(row.store_id)
    if (row.created_by === "agent") byAgent += 1
    if (row.review_state === "needs_review") waiting += 1
    if (row.status === "captured") {
      captured += 1
      volume += Number(row.total)
    }
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every purchase from a connected store. Prices are computed by the API from the verified spec, then paid with
          the saved sandbox buyer and captured.
          {checkOn &&
            " An agent's order is held first and checked against what the buyer asked for: a clean match is captured, anything off waits for the buyer."}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="orders">
          <Ticker value={rows.length} />
        </Tile>
        <Tile label="captured">
          <span className="text-ok">
            <Ticker value={captured} />
          </span>
        </Tile>
        <Tile label="captured volume (sandbox USD)">
          $<Ticker value={volume} decimals={2} />
        </Tile>
        <Tile label={"bought by an agent, across " + storeIds.size + (storeIds.size === 1 ? " store" : " stores")}>
          <Ticker value={byAgent} />
        </Tile>
      </div>

      {checkOn && waiting > 0 && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          {waiting === 1 ? "1 order is" : waiting + " orders are"} on hold, waiting for the buyer to confirm. Nothing
          has been charged for {waiting === 1 ? "it" : "them"}.
        </p>
      )}

      {error && <ErrorNote>{error}</ErrorNote>}

      <Card className="flex h-[560px] flex-col overflow-hidden">
        <div className="flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2">
          <label className="flex h-8 w-full max-w-64 items-center gap-2 rounded-lg border border-border px-2.5">
            <Search className="size-3.5 text-muted-foreground" />
            <span className="sr-only">Filter orders</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter orders"
              className="w-full min-w-0 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground/70"
            />
          </label>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-1.5 animate-pulse rounded-full bg-ok" /> updates every 3s
            </span>
            <Switch checked={grouped} onChange={setGrouped} label="Group by store" />
          </div>
        </div>
        <div ref={wrapper} className="min-h-0 flex-1">
          <AgGridReact<OrderRow>
            theme={calmTheme}
            rowData={NO_ROWS}
            columnDefs={columnDefs}
            defaultColDef={{ sortable: true, resizable: true, suppressMovable: true }}
            getRowId={(params: GetRowIdParams<OrderRow>) => String(params.data.id)}
            // taller than the theme's 44 so the 44px Review button has air around it
            rowHeight={52}
            enableCellSpan
            context={gridContext}
            tooltipShowDelay={300}
            onGridReady={onGridReady}
            animateRows
            suppressCellFocus
            overlayNoRowsTemplate='<span style="color: var(--muted-foreground); font-size: 13px">No orders yet. Ask the agent to buy something, or use Test buy on a verified item.</span>'
          />
        </div>
      </Card>

      <AnimatePresence>
        {reviewOrder && (
          <ReviewDrawer key={reviewOrder.id} order={reviewOrder} onClose={closeReview} onDecided={reviewDecided} />
        )}
      </AnimatePresence>
    </div>
  )
}
