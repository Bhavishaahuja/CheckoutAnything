// Screen 4: orders. Two views of the same question, "did the agent buy the right thing?":
//   Intent review  Leash's held orders, each next to its mandate, decided in the row
//   Purchases      everything bought through a connected store's buy endpoint

import type { ColDef, GetRowIdParams } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import { Bot, Check, Hand, ReceiptText, RotateCcw, Search, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { Card, CopyId, ErrorNote, Pill, Switch } from "@/components/bits"
import { ColumnsMenu } from "@/components/grid/ColumnsMenu"
import { createOverlayStore, GridOverlay } from "@/components/grid/GridOverlay"
import { LeashOrdersGrid } from "@/components/LeashOrdersGrid"
import { NumberTicker } from "@/components/magicui/number-ticker"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { clockTime, money } from "@/lib/format"
import { flashGridRow } from "@/lib/gridFlash"
import { useGridLayout } from "@/lib/gridState"
import { calmTheme } from "@/lib/gridTheme"
import type { Order } from "@/lib/types"
import { useGridRows } from "@/lib/useGridRows"
import { cn } from "@/lib/utils"

type View = "review" | "purchases"

const POLL_MS = 3000

interface OrderRow extends Order {
  seen_at: number
}

// the grid starts empty, rows then arrive as transactions
const NO_ROWS: OrderRow[] = []
const defaultColDef = { sortable: true, resizable: true }

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

export function OrdersPage({ active, refreshKey, onGoToAgent }: { active: boolean; refreshKey: number; onGoToAgent: () => void }) {
  const [view, setView] = useState<View>("review")
  const [loaded, setLoaded] = useState(false)
  const layout = useGridLayout("purchases")
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
        setLoaded(true)
        setRows((previous) => {
          const before = new Map(previous.map((row) => [row.id, row]))
          let changed = orders.length !== previous.length
          const next = orders.map((order) => {
            const old = before.get(order.id)
            if (old && old.status === order.status && old.capture_id === order.capture_id) return old
            changed = true
            // orders already there on first load don't flash, new ones do
            return { ...order, seen_at: firstLoad.current ? 0 : Date.now() }
          })
          firstLoad.current = false
          return changed ? next : previous
        })
      } catch (problem) {
        if (!cancelled) {
          setError(problem instanceof Error ? problem.message : "Couldn't load orders")
          setLoaded(true)
        }
      }
    }

    void load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [active, refreshKey])

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

  const overlay = useMemo(
    () =>
      createOverlayStore({
        loading: { title: "Loading purchases..." },
        empty: { title: "No purchases yet" },
        noMatch: { title: "No purchase matches that filter", actionLabel: "Clear the filter", onAction: () => {} },
      }),
    []
  )
  const context = useMemo(() => ({ overlay }), [overlay])
  useEffect(() => {
    overlay.set({
      loading: { title: "Loading purchases..." },
      empty: {
        icon: <ReceiptText />,
        title: "No purchases yet",
        hint: "Ask the shopping agent to buy something from a connected store, or use Test buy on a verified item.",
        actionLabel: "Send an agent shopping",
        onAction: onGoToAgent,
      },
      noMatch: { title: "No purchase matches that filter", actionLabel: "Clear the filter", onAction: () => setSearch("") },
    })
  }, [overlay, onGoToAgent])

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
    [grouped]
  )

  let captured = 0
  let volume = 0
  let byAgent = 0
  const storeIds = new Set<number>()
  for (const row of rows) {
    storeIds.add(row.store_id)
    if (row.created_by === "agent") byAgent += 1
    if (row.status === "captured") {
      captured += 1
      volume += Number(row.total)
    }
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Orders</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {view === "review"
              ? "Leash holds each agent order at PayPal while Claude checks it against what the shopper asked for. Clean matches capture on their own. The rest wait here for you."
              : "Every purchase from a connected store. Prices are computed by the API from the verified spec, then paid with the saved sandbox buyer and captured."}
          </p>
        </div>
        <div className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5" role="group" aria-label="Which orders">
          {(["review", "purchases"] as View[]).map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={view === entry}
              onClick={() => setView(entry)}
              className={cn(
                "h-8 rounded-md px-3 text-[13px] font-medium transition-colors",
                view === entry ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {entry === "review" ? "Intent review (Leash)" : "Purchases"}
            </button>
          ))}
        </div>
      </div>

      {/* both stay mounted, so each keeps its scroll position and its live updates */}
      <Card className={cn("h-[640px] overflow-hidden", view !== "review" && "hidden")}>
        <LeashOrdersGrid active={active && view === "review"} />
      </Card>

      <div className={cn("flex flex-col gap-5", view !== "purchases" && "hidden")}>

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
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-1.5 animate-pulse rounded-full bg-ok" /> updates every 3s
            </span>
            <Switch checked={grouped} onChange={setGrouped} label="Group by store" />
            <ColumnsMenu gridApi={gridApi} />
            <Button size="sm" variant="ghost" onClick={layout.resetLayout} disabled={!layout.hasSaved} title="Put the columns, sort and filters back to the defaults">
              <RotateCcw /> <span className="hidden sm:inline">Reset layout</span>
            </Button>
          </div>
        </div>
        <div ref={wrapper} className="min-h-0 flex-1">
          <AgGridReact<OrderRow>
            key={layout.layoutVersion}
            theme={calmTheme}
            rowData={NO_ROWS}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            context={context}
            getRowId={(params: GetRowIdParams<OrderRow>) => String(params.data.id)}
            enableCellSpan
            initialState={layout.initialState}
            onStateUpdated={layout.onStateUpdated}
            loading={!loaded}
            overlayComponent={GridOverlay}
            onGridReady={onGridReady}
            animateRows
          />
        </div>
      </Card>
      </div>
    </div>
  )
}
