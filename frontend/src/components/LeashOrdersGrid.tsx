// Leash inside Checkout Anything: every agent order next to what the shopper asked for.
//
// Orders that need a human are pinned to the top with Approve and Reject right in the row, and
// drop into the list once decided. Column groups put the mandate, the order and the decision
// side by side, with the field that differs marked in both. Status changes arrive as row
// transactions and flash the status cell, so the grid never reloads or loses its place.

import type { CellClassParams, ColDef, ColGroupDef, GetRowIdParams, RowClassRules } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import {
  Ban,
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Eye,
  Hand,
  LoaderCircle,
  EqualNot,
  ReceiptText,
  RotateCcw,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  X,
  Zap,
} from "lucide-react"
import { animate } from "motion"
import { AnimatePresence, motion } from "motion/react"
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react"

import { ErrorNote, Pill } from "@/components/bits"
import { ColumnsMenu } from "@/components/grid/ColumnsMenu"
import { createOverlayStore, GridOverlay, type OverlayStore } from "@/components/grid/GridOverlay"
import { CountRoll, POP, Press } from "@/components/grid/motion"
import { Button } from "@/components/ui/button"
import { USE_MOCK } from "@/lib/api"
import { clockTime, duration, money } from "@/lib/format"
import { FindCell, FindText, useGridFind, type FindStore } from "@/lib/gridFind"
import { flashGridCells } from "@/lib/gridFlash"
import { useGridLayout } from "@/lib/gridState"
import { calmTheme } from "@/lib/gridTheme"
import { leash, LEASH_URL, LeashError, type LeashOrder, type LeashStats } from "@/lib/leash"
import { useGridRows } from "@/lib/useGridRows"
import { cn } from "@/lib/utils"

const POLL_MS = 3000

type Kind = "review" | "checking" | "waiting" | "auto" | "approved" | "voided" | "disputed" | "failed"

interface OrderRow extends LeashOrder {
  kind: Kind
}

function kindOf(order: LeashOrder, disputed: boolean): Kind {
  if (disputed) return "disputed"
  if (order.status === "authorized") return order.review_state === "needs_review" ? "review" : "checking"
  if (order.status === "created") return "waiting"
  if (order.status === "captured") return order.review_state === "approved" ? "approved" : "auto"
  if (order.status === "voided") return "voided"
  return "failed"
}

// every state has a colour, an icon and words, so colour is never the only signal
const KINDS: Record<Kind, { label: string; tone: "ok" | "bad" | "warn" | "info" | "muted"; icon: ReactNode; rowClass: string }> = {
  review: { label: "Needs review", tone: "warn", icon: <Hand />, rowClass: "order-review" },
  checking: { label: "Held, being checked", tone: "info", icon: <LoaderCircle className="spin-slow" />, rowClass: "" },
  waiting: { label: "Waiting on buyer", tone: "muted", icon: <Clock />, rowClass: "" },
  auto: { label: "Auto-captured", tone: "ok", icon: <Zap />, rowClass: "order-captured" },
  approved: { label: "Approved, captured", tone: "ok", icon: <UserCheck />, rowClass: "order-captured" },
  voided: { label: "Voided", tone: "muted", icon: <Ban />, rowClass: "order-voided" },
  disputed: { label: "Disputed", tone: "bad", icon: <Scale />, rowClass: "order-disputed" },
  failed: { label: "Failed", tone: "bad", icon: <X />, rowClass: "order-failed" },
}

// which cells a mismatched field lights up, on the mandate side and on the order side
const MISMATCH_CELLS: Record<string, string[]> = {
  color: ["m_color", "o_color"],
  size: ["m_size", "o_size"],
  item: ["m_item", "o_item"],
  model: ["m_item", "o_item"],
  substitution: ["m_item", "o_item"],
  event_date: ["m_item", "o_item"],
  extra_item: ["o_item"],
  quantity: ["m_qty", "o_qty"],
  price: ["m_cap", "o_total"],
  merchant: ["m_store", "o_store"],
}

function isMismatch(row: OrderRow | undefined, colId: string) {
  for (const field of row?.intent_check?.mismatched_fields || []) {
    if (MISMATCH_CELLS[field]?.includes(colId)) return true
  }
  return false
}

// ---- a tiny store for which rows have a decision in flight ----

type Busy = Record<number, "approve" | "reject">

function createBusyStore() {
  let value: Busy = {}
  const listeners = new Set<() => void>()
  return {
    get: () => value,
    set: (next: Busy) => {
      value = next
      for (const listener of listeners) listener()
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

interface OrdersContext {
  overlay: OverlayStore
  find: FindStore
  busy: ReturnType<typeof createBusyStore>
  // the row is on screen with its buttons: get its review link and start the clock
  open: (orderId: number) => void
  decide: (orderId: number, action: "approve" | "reject") => void
  fastMs: number
}

type CellProps = CustomCellRendererProps<OrderRow, unknown, OrdersContext>

// ---- cells ----

function ValueCell(props: CellProps) {
  const colId = props.column?.getColId() || ""
  const text = props.valueFormatted ?? (props.value === null || props.value === undefined ? "" : String(props.value))
  const off = isMismatch(props.data, colId)
  if (!text) return <span className="text-muted-foreground/60">Not said</span>
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {off && (
        <motion.span className="shrink-0 text-bad" role="img" aria-label="Does not match" initial={{ scale: 0, rotate: -45 }} animate={{ scale: 1, rotate: 0 }} transition={POP}>
          <EqualNot className="size-3.5" strokeWidth={2.5} />
        </motion.span>
      )}
      <span className="truncate">
        <FindText text={text} rowId={props.node.id || ""} colId={colId} store={props.context.find} />
      </span>
    </span>
  )
}

function RiskCell({ data }: CellProps) {
  const score = data?.intent_check?.risk_score
  if (score === null || score === undefined) return <span className="text-muted-foreground/60">Not scored</span>
  const high = score >= 60
  const medium = score >= 30 && score < 60
  return (
    <Pill tone={high ? "bad" : medium ? "warn" : "ok"}>
      {high ? <ShieldAlert className="size-3.5" /> : medium ? <Eye className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
      <span className="tabular-nums">{score}</span> {high ? "High" : medium ? "Medium" : "Low"}
    </Pill>
  )
}

function StatusCell({ data }: CellProps) {
  if (!data) return null
  const look = KINDS[data.kind]
  // the pill springs in again every time the order moves to a new state
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span key={data.kind} className="inline-flex" initial={{ scale: 0.6, opacity: 0, y: 6 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.8, opacity: 0, y: -6 }} transition={POP}>
        <Pill tone={look.tone} className="[&_svg]:size-3.5">
          {look.icon} {look.label}
        </Pill>
      </motion.span>
    </AnimatePresence>
  )
}

function DecideTimeCell({ data, context }: CellProps) {
  if (!data) return null
  const approval = data.approval
  if (!approval || !approval.action) {
    if (data.kind === "review") return <span className="text-warn">Waiting for you</span>
    if (data.kind === "auto" || data.kind === "disputed") return <span className="text-muted-foreground/70">No human needed</span>
    return <span className="text-muted-foreground/70">Not decided</span>
  }
  if (!approval.decision_ms) return <span className="text-muted-foreground/70">Not measured</span>
  const fast = approval.action === "approve" && approval.decision_ms < context.fastMs
  return (
    <span className="flex items-center gap-2">
      <span className="font-mono tabular-nums">{duration(approval.decision_ms)}</span>
      {fast && (
        <motion.span
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ ...POP, delay: 0.15 }}
          className="inline-flex h-5 items-center gap-1 rounded-md bg-warn-soft px-1.5 text-[11px] leading-none font-medium whitespace-nowrap text-warn"
          title={"Approved in under " + context.fastMs / 1000 + "s. The rubber-stamp watch counts these."}
        >
          <Zap className="size-3" aria-hidden /> Fast approval
        </motion.span>
      )}
    </span>
  )
}

function ActionsCell({ data, context }: CellProps) {
  const busy = useSyncExternalStore(context.busy.subscribe, context.busy.get)
  const orderId = data?.id
  const waiting = data?.kind === "review"
  useEffect(() => {
    if (waiting && orderId !== undefined) context.open(orderId)
  }, [context, orderId, waiting])

  if (!data || !waiting) return null
  const mine = busy[data.id]
  const name = data.items[0]?.name || "this order"
  return (
    <motion.span className="flex items-center gap-1.5" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={POP}>
      <Press disabled={Boolean(mine)}>
      <Button
        size="sm"
        className="h-7 bg-ok px-2 text-white dark:text-background"
        disabled={Boolean(mine)}
        aria-label={"Approve order " + data.id + ", " + name + ", and capture " + money(data.total, data.currency)}
        onClick={() => context.decide(data.id, "approve")}
      >
        {mine === "approve" ? <LoaderCircle className="spin-slow" /> : <Check strokeWidth={3} />}
        {mine === "approve" ? "Capturing" : "Approve"}
      </Button>
      </Press>
      <Press disabled={Boolean(mine)}>
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-2"
        disabled={Boolean(mine)}
        aria-label={"Reject order " + data.id + ", " + name + ", and release the hold"}
        onClick={() => context.decide(data.id, "reject")}
      >
        {mine === "reject" ? <LoaderCircle className="spin-slow" /> : <X strokeWidth={3} />}
        {mine === "reject" ? "Voiding" : "Reject"}
      </Button>
      </Press>
    </motion.span>
  )
}

const mismatchRules = {
  "cell-mismatch": (params: CellClassParams<OrderRow>) => isMismatch(params.data, params.column.getColId()),
}

const rowClassRules: RowClassRules<OrderRow> = {
  "order-review": (params) => params.data?.kind === "review",
  "order-captured": (params) => params.data?.kind === "auto" || params.data?.kind === "approved",
  "order-voided": (params) => params.data?.kind === "voided",
  "order-disputed": (params) => params.data?.kind === "disputed",
  "order-failed": (params) => params.data?.kind === "failed",
}

const findable = { findable: true }

function compare(a: unknown, b: unknown) {
  return Number(a) - Number(b)
}

const columnDefs: (ColDef<OrderRow> | ColGroupDef<OrderRow>)[] = [
  {
    headerName: "Mandate: what the shopper asked for",
    headerClass: "group-mandate",
    marryChildren: true,
    children: [
      { headerName: "In their words", colId: "m_request", valueGetter: (p) => p.data?.mandate?.raw_request || "", context: findable, cellRenderer: FindCell, tooltipValueGetter: (p) => p.value || undefined, width: 200, filter: true },
      { headerName: "Item", colId: "m_item", valueGetter: (p) => p.data?.mandate?.rules.item || "", context: findable, width: 122 },
      { headerName: "Color", colId: "m_color", valueGetter: (p) => p.data?.mandate?.rules.color || "", context: findable, width: 88 },
      { headerName: "Size", colId: "m_size", valueGetter: (p) => p.data?.mandate?.rules.size || "", context: findable, width: 72 },
      { headerName: "Qty", colId: "m_qty", valueGetter: (p) => p.data?.mandate?.rules.quantity ?? "", width: 64 },
      {
        headerName: "Cap",
        colId: "m_cap",
        valueGetter: (p) => p.data?.mandate?.max_price ?? "",
        valueFormatter: (p) =>
          p.value ? (p.data?.mandate?.max_price_inclusive ? "up to " : "under ") + money(p.value, p.data?.mandate?.rules.currency || "USD") : "",
        comparator: compare,
        cellClass: "tabular-nums",
        width: 116,
      },
      // the two Store columns start hidden to keep the comparison on one screen (Columns menu)
      { headerName: "Store", colId: "m_store", valueGetter: (p) => p.data?.mandate?.merchant || "", context: findable, width: 150, initialHide: true },
    ],
  },
  {
    headerName: "Order: what the agent bought",
    headerClass: "group-order",
    marryChildren: true,
    children: [
      {
        headerName: "Item",
        colId: "o_item",
        valueGetter: (p) => {
          const items = p.data?.items || []
          if (items.length === 0) return ""
          return items[0].name + (items.length > 1 ? " +" + (items.length - 1) + " more" : "")
        },
        context: findable,
        width: 158,
        filter: true,
      },
      { headerName: "Color", colId: "o_color", valueGetter: (p) => p.data?.items[0]?.color || "", context: findable, width: 88 },
      { headerName: "Size", colId: "o_size", valueGetter: (p) => p.data?.items[0]?.size || "", context: findable, width: 72 },
      { headerName: "Qty", colId: "o_qty", valueGetter: (p) => p.data?.items[0]?.quantity ?? "", width: 64 },
      {
        headerName: "Total",
        colId: "o_total",
        valueGetter: (p) => p.data?.total ?? "",
        valueFormatter: (p) => (p.data ? money(p.data.total, p.data.currency) : ""),
        comparator: compare,
        cellClass: "font-mono tabular-nums",
        width: 96,
      },
      { headerName: "Store", colId: "o_store", valueGetter: (p) => p.data?.merchant || "Fernwood Supply Co", context: findable, width: 150, initialHide: true },
      {
        headerName: "Agent",
        colId: "o_agent",
        valueGetter: (p) => p.data?.agent_name || "",
        cellRenderer: (p: CellProps) =>
          p.value ? (
            <Pill tone="info">
              <Bot className="size-3.5" /> {String(p.value)}
            </Pill>
          ) : (
            <span className="text-muted-foreground/60">Not named</span>
          ),
        width: 120,
        filter: true,
        initialHide: true,
      },
    ],
  },
  {
    headerName: "Decision",
    headerClass: "group-decision",
    marryChildren: true,
    children: [
      { headerName: "Risk", colId: "risk", valueGetter: (p) => p.data?.intent_check?.risk_score ?? null, cellRenderer: RiskCell, width: 124 },
      {
        headerName: "Claude's reason",
        colId: "reason",
        valueGetter: (p) => p.data?.intent_check?.reason || (p.data?.kind === "checking" ? "Claude is checking it against the mandate" : "No reason was saved"),
        context: findable,
        cellRenderer: FindCell,
        tooltipValueGetter: (p) => p.value || undefined,
        width: 280,
        filter: true,
      },
      { headerName: "Status", colId: "status", valueGetter: (p) => (p.data ? KINDS[p.data.kind].label : ""), cellRenderer: StatusCell, enableCellChangeFlash: false, width: 190, filter: true },
      { headerName: "Time to decide", colId: "decide_ms", valueGetter: (p) => p.data?.approval?.decision_ms ?? null, cellRenderer: DecideTimeCell, headerTooltip: "From the order showing on screen to the tap, on Leash's own clock", width: 200 },
      { headerName: "Placed", colId: "created_at", valueGetter: (p) => p.data?.created_at || "", valueFormatter: (p) => clockTime(p.value), sort: "desc", cellClass: "text-muted-foreground tabular-nums", width: 118 },
    ],
  },
  {
    headerName: "Decide",
    colId: "actions",
    pinned: "right",
    lockPinned: true,
    lockVisible: true,
    sortable: false,
    resizable: false,
    suppressMovable: true,
    cellRenderer: ActionsCell,
    width: 208,
  },
]

const defaultColDef: ColDef<OrderRow> = {
  sortable: true,
  resizable: true,
  cellRenderer: ValueCell,
  cellClassRules: mismatchRules,
}

const NO_ROWS: OrderRow[] = []

function SignIn({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await leash.login(password)
      onDone()
    } catch (problem) {
      setError(problem instanceof LeashError && problem.status === 401 ? "That isn't the password" : problem instanceof Error ? problem.message : "Sign in failed")
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="mx-auto flex h-full max-w-sm flex-col items-center justify-center gap-3 px-4 text-center">
      <ShieldCheck className="size-6 text-muted-foreground" aria-hidden />
      <h2 className="text-sm font-semibold">Sign in to Leash</h2>
      <p className="text-[13px] text-pretty text-muted-foreground">
        Agent orders are held and checked by the Leash API at {LEASH_URL.replace(/^https?:\/\//, "")}. Enter its demo merchant password to
        review them here.
      </p>
      <label className="w-full text-left text-xs font-medium">
        Password
        <input
          type="password"
          value={password}
          autoComplete="current-password"
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-border bg-card px-2.5 text-sm font-normal outline-none focus:border-primary"
        />
      </label>
      {error && (
        <div className="w-full text-left">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
      <Button type="submit" className="w-full" disabled={busy || !password}>
        {busy ? "Signing in" : "Sign in"}
      </Button>
    </form>
  )
}

export function LeashOrdersGrid({ active }: { active: boolean }) {
  const layout = useGridLayout("leash-orders")
  const wrapper = useRef<HTMLDivElement>(null)
  const [signedIn, setSignedIn] = useState(() => leash.signedIn())
  const [rows, setRows] = useState<OrderRow[]>([])
  const [stats, setStats] = useState<LeashStats | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [placing, setPlacing] = useState(false)

  const previous = useRef<Map<number, OrderRow>>(new Map())
  // rows that changed state since the last poll, to flash once the grid has them
  const changed = useRef<{ id: number; kind: Kind; unpinnedFrom: number | null }[]>([])

  const refresh = useCallback(async () => {
    try {
      const [orders, nextStats, disputes] = await Promise.all([leash.listOrders(), leash.stats(), leash.listDisputes().catch(() => [])])
      const disputed = new Set(disputes.map((dispute) => dispute.order_id))
      const before = previous.current
      const next = new Map<number, OrderRow>()
      const list: OrderRow[] = []
      for (const order of orders) {
        const row: OrderRow = { ...order, kind: kindOf(order, disputed.has(order.id)) }
        const old = before.get(order.id)
        if (old && JSON.stringify(old) === JSON.stringify(row)) {
          next.set(order.id, old)
          list.push(old)
          continue
        }
        if (before.size > 0 && (!old || old.kind !== row.kind)) {
          // where a pinned row sits right now, so it can be seen travelling to its new place
          let unpinnedFrom: number | null = null
          if (old && old.kind === "review" && wrapper.current) {
            const element = wrapper.current.querySelector<HTMLElement>('.ag-row[row-id="' + order.id + '"]')
            if (element) unpinnedFrom = element.getBoundingClientRect().top
          }
          changed.current.push({ id: order.id, kind: row.kind, unpinnedFrom })
        }
        next.set(order.id, row)
        list.push(row)
      }
      previous.current = next
      setRows((was) => (was.length === list.length && was.every((row, index) => row === list[index]) ? was : list))
      setStats(nextStats)
      setError(null)
      setLoaded(true)
    } catch (problem) {
      if (problem instanceof LeashError && problem.status === 401) setSignedIn(false)
      else setError(problem instanceof Error ? problem.message : "Couldn't load orders from Leash")
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    if (!active || !signedIn) return
    let stopped = false
    const tick = () => {
      if (!stopped && !document.hidden) void refresh()
    }
    tick()
    const timer = setInterval(tick, POLL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [active, signedIn, refresh])

  // needs-review orders are pinned to the top, everything else is the list
  const pinned = useMemo(() => rows.filter((row) => row.kind === "review"), [rows])
  const body = useMemo(() => rows.filter((row) => row.kind !== "review"), [rows])
  const { gridApi, onGridReady } = useGridRows(body, (row) => String(row.id))
  const find = useGridFind(gridApi)

  // ---- deciding ----

  const busy = useMemo(() => createBusyStore(), [])
  const tokens = useRef<Map<number, Promise<string>>>(new Map())
  const openedAt = useRef<Map<number, number>>(new Map())
  const activeRef = useRef(active)
  useEffect(() => {
    activeRef.current = active
  })

  const open = useCallback((orderId: number) => {
    if (!activeRef.current || tokens.current.has(orderId)) return
    openedAt.current.set(orderId, Date.now())
    const link = leash.openReview(orderId)
    tokens.current.set(orderId, link)
    link.catch(() => tokens.current.delete(orderId))
  }, [])

  const decide = useCallback(
    async (orderId: number, action: "approve" | "reject") => {
      if (busy.get()[orderId]) return // a second click while the first is in flight
      busy.set({ ...busy.get(), [orderId]: action })
      try {
        open(orderId)
        const token = await (tokens.current.get(orderId) || leash.openReview(orderId))
        await leash.decide(token, action, Date.now() - (openedAt.current.get(orderId) || Date.now()))
        tokens.current.delete(orderId)
        await refresh()
      } catch (problem) {
        tokens.current.delete(orderId)
        setError(problem instanceof Error ? problem.message : "The decision didn't go through")
        await refresh()
      } finally {
        const rest = { ...busy.get() }
        delete rest[orderId]
        busy.set(rest)
      }
    },
    [busy, open, refresh]
  )

  const placeDemoOrder = useCallback(async () => {
    setPlacing(true)
    setError(null)
    try {
      await leash.demoOrder()
      await refresh()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The demo order failed")
    } finally {
      setPlacing(false)
    }
  }, [refresh])

  // ---- context ----

  const overlay = useMemo(
    () =>
      createOverlayStore({
        loading: { title: "Loading orders from Leash..." },
        empty: { title: "No orders yet" },
        noMatch: { title: "No order matches", actionLabel: "Clear the search", onAction: () => {} },
      }),
    []
  )
  const fastMs = stats?.fast_threshold_ms || 2000
  const context = useMemo<OrdersContext>(
    () => ({ overlay, find: find.store, busy, open, decide: (id, action) => void decide(id, action), fastMs }),
    [overlay, find.store, busy, open, decide, fastMs]
  )

  const { setTerm } = find
  useEffect(() => {
    overlay.set({
      loading: { title: "Loading orders from Leash...", step: "Asking " + LEASH_URL.replace(/^https?:\/\//, "") },
      empty: {
        icon: <ReceiptText />,
        title: "No orders yet. Run a demo order",
        hint: "It places a real held order through Leash, which Claude then checks against its mandate.",
        actionLabel: placing ? "Placing the order" : "Run a demo order",
        onAction: () => void placeDemoOrder(),
        busy: placing,
      },
      noMatch: { title: "No order matches that search", actionLabel: "Clear the search", onAction: () => setTerm("") },
    })
  }, [overlay, placing, placeDemoOrder, setTerm])

  useEffect(() => {
    if (gridApi && !gridApi.isDestroyed()) gridApi.setGridOption("quickFilterText", find.term)
  }, [gridApi, find.term])

  // an order at the wrong store brings the two Store columns out, so the mismatch has a cell
  // to show in on both sides
  const storeMismatch = rows.some((row) => row.intent_check?.mismatched_fields?.includes("merchant"))
  const storesShown = useRef(false)
  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed() || !storeMismatch || storesShown.current) return
    storesShown.current = true
    if (!layout.hasSaved) gridApi.setColumnsVisible(["m_store", "o_store"], true)
  }, [gridApi, storeMismatch, layout.hasSaved])

  // ---- the status cell flashes when an order moves, and an unpinned row travels down ----

  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed() || changed.current.length === 0) return
    const moves = changed.current
    changed.current = []
    for (const move of moves) {
      const tone = move.kind === "auto" || move.kind === "approved" ? "ok" : move.kind === "voided" || move.kind === "failed" || move.kind === "disputed" ? "bad" : "new"
      flashGridCells(gridApi, wrapper.current, String(move.id), ["status", "decide_ms"], tone)
      if (move.unpinnedFrom === null) continue
      const from = move.unpinnedFrom
      const node = gridApi.getRowNode(String(move.id))
      if (node) gridApi.ensureNodeVisible(node)
      // two frames: one for the grid to draw the row in the list, one to measure it
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          const container = wrapper.current
          if (!container || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
          const cells: HTMLElement[] = []
          let top: number | null = null
          for (const element of container.querySelectorAll<HTMLElement>('.ag-row[row-id="' + move.id + '"]')) {
            if (top === null) top = element.getBoundingClientRect().top
            for (const cell of element.querySelectorAll<HTMLElement>(".ag-cell")) cells.push(cell)
          }
          if (top === null || cells.length === 0) return
          animate(cells, { y: [from - top, 0] }, { duration: 0.55, ease: [0.2, 0, 0, 1] })
        })
      )
    }
  }, [gridApi, rows])

  // ---- the strip above the grid ----

  let fastApprovals = 0
  for (const row of rows) {
    const approval = row.approval
    if (approval && approval.action === "approve" && approval.decision_ms && approval.decision_ms < fastMs) fastApprovals += 1
  }
  const watchOn = Boolean(stats?.rubber_stamp_active)

  // another fast approval makes the strip jolt, so it is noticed the moment it happens
  const strip = useRef<HTMLDivElement>(null)
  const lastFast = useRef<number | null>(null)
  useEffect(() => {
    const grew = lastFast.current !== null && fastApprovals > lastFast.current
    lastFast.current = fastApprovals
    if (!grew || !strip.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    animate(strip.current, { scale: [1, 1.07, 1], rotate: [0, -1.5, 1.5, 0] }, { duration: 0.5, ease: "easeOut" })
  }, [fastApprovals])

  if (!signedIn) {
    return (
      <SignIn
        onDone={() => {
          setLoaded(false)
          setSignedIn(true)
        }}
      />
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2">
        <div className="flex h-8 items-center gap-1 rounded-lg border border-border pr-1 pl-2.5 focus-within:border-primary">
          <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <input
            value={find.term}
            onChange={(event) => find.setTerm(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                if (event.shiftKey) find.previous()
                else find.next()
              }
              if (event.key === "Escape") find.setTerm("")
            }}
            placeholder="Search orders"
            aria-label="Search orders: filters the rows and highlights matches"
            className="w-40 min-w-0 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground/70"
          />
          {find.term.trim() !== "" && (
            <>
              <span className="px-1 text-xs whitespace-nowrap text-muted-foreground tabular-nums" role="status" aria-live="polite">
                {find.count === 0 ? "No matches" : <><CountRoll value={find.current} /> of {find.count}</>}
              </span>
              <button type="button" onClick={find.previous} disabled={find.count === 0} aria-label="Previous match" className="flex size-6 items-center justify-center rounded-md hover:bg-muted disabled:opacity-40">
                <ChevronUp className="size-4" />
              </button>
              <button type="button" onClick={find.next} disabled={find.count === 0} aria-label="Next match" className="flex size-6 items-center justify-center rounded-md hover:bg-muted disabled:opacity-40">
                <ChevronDown className="size-4" />
              </button>
            </>
          )}
        </div>

        {/* the rubber-stamp watch: approvals too fast to have been read */}
        <motion.div
          ref={strip}
          layout
          role="status"
          aria-label={"Rubber-stamp risk: " + fastApprovals + (fastApprovals === 1 ? " approval" : " approvals") + " under " + fastMs / 1000 + " seconds"}
          className={cn(
            "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px]",
            fastApprovals > 0 ? "bg-warn-soft font-medium text-warn" : "bg-muted text-muted-foreground"
          )}
          title="An approval this fast was almost certainly not read. Three in a row turn Leash's sharp mode on."
        >
          <Zap className="size-3.5" aria-hidden />
          <span>Rubber-stamp risk:</span> <CountRoll value={fastApprovals} />
          <span>
            {fastApprovals === 1 ? "approval" : "approvals"} under {fastMs / 1000}s
          </span>
          <AnimatePresence>
            {watchOn && (
              <motion.span key="sharp" initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0, opacity: 0 }} transition={POP} className="ml-1 rounded-md bg-warn px-1.5 py-0.5 text-[11px] text-card">
                Sharp mode is on
              </motion.span>
            )}
          </AnimatePresence>
        </motion.div>

        <AnimatePresence initial={false}>
          {pinned.length > 0 && (
            <motion.span key="pinned" layout initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Hand className="size-3.5 text-warn" aria-hidden /> <CountRoll value={pinned.length} /> pinned until you decide
            </motion.span>
          )}
        </AnimatePresence>

        <div className="ml-auto flex items-center gap-1.5">
          <span className="mr-1 hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
            <span className="size-1.5 animate-pulse rounded-full bg-ok" /> live{USE_MOCK ? " (mock)" : ""}
          </span>
          <Button size="sm" variant="outline" onClick={() => void placeDemoOrder()} disabled={placing}>
            {placing ? <LoaderCircle className="spin-slow" /> : <ReceiptText />} <span className="hidden sm:inline">Run a demo order</span>
          </Button>
          <ColumnsMenu gridApi={gridApi} />
          <Button size="sm" variant="ghost" onClick={layout.resetLayout} disabled={!layout.hasSaved} title="Put the columns, sort and filters back to the defaults">
            <RotateCcw /> <span className="hidden sm:inline">Reset layout</span>
          </Button>
        </div>
      </div>

      {error && (
        <div className="shrink-0 px-4 pt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <div ref={wrapper} className="min-h-0 flex-1">
        <AgGridReact<OrderRow>
          key={layout.layoutVersion}
          theme={calmTheme}
          rowData={NO_ROWS}
          pinnedTopRowData={pinned}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          context={context}
          getRowId={(params: GetRowIdParams<OrderRow>) => String(params.data.id)}
          rowClassRules={rowClassRules}
          initialState={layout.initialState}
          onStateUpdated={layout.onStateUpdated}
          loading={!loaded}
          overlayComponent={GridOverlay}
          onGridReady={onGridReady}
          animateRows
          tooltipShowDelay={400}
          groupHeaderHeight={34}
        />
      </div>
    </div>
  )
}
