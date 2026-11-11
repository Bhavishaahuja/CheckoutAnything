// The one Orders grid: every purchase from a connected store, and what Check decided about it.
//
// Orders on hold are pinned to the top until a human decides, then travel down into the list.
// Column groups read left to right: the order, what Check made of it, the decision, the PayPal
// ids. A status change arrives as a row transaction and flashes its cells, so the grid never
// reloads or loses its place. Reviewing happens on the real confirm page: the Review button
// only opens the drawer, and nothing here approves, rejects or asks for a review link.

import type { CellClassParams, ColDef, ColGroupDef, GetRowIdParams, RowClassRules } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import {
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  EqualNot,
  Hand,
  Hourglass,
  ReceiptText,
  RotateCcw,
  Search,
  ShieldCheck,
  ShieldQuestion,
  Undo2,
  X,
  Zap,
} from "lucide-react"
import { animate } from "motion"
import { AnimatePresence, motion } from "motion/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { CopyId, Pill, Switch } from "@/components/bits"
import { ColumnsMenu } from "@/components/grid/ColumnsMenu"
import { createOverlayStore, GridOverlay, type OverlayStore } from "@/components/grid/GridOverlay"
import { CountRoll, POP } from "@/components/grid/motion"
import { Button } from "@/components/ui/button"
import { CHECK_URL } from "@/lib/appLinks"
import { checkNumber, clockTime, decisionTime, money } from "@/lib/format"
import { FindCell, FindText, useGridFind, type FindStore } from "@/lib/gridFind"
import { flashGridCells, flashGridRow } from "@/lib/gridFlash"
import { useGridLayout } from "@/lib/gridState"
import { calmTheme } from "@/lib/gridTheme"
import { heldLabel } from "@/lib/shortReason"
import type { AgentHeldRate, CheckStats, Order } from "@/lib/types"
import { useGridRows } from "@/lib/useGridRows"
import { cn } from "@/lib/utils"

export interface OrderRow extends Order {
  seen_at: number
}

// an approval faster than this was almost certainly not read (Check's own threshold)
const FAST_MS = 2000

// room enough to keep a column pinned beside the scrolling ones
const WIDE_SCREEN = "(min-width: 1024px)"

function useWideScreen() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_SCREEN).matches)
  useEffect(() => {
    const query = window.matchMedia(WIDE_SCREEN)
    const update = () => setWide(query.matches)
    query.addEventListener("change", update)
    return () => query.removeEventListener("change", update)
  }, [])
  return wide
}

// on hold at PayPal, waiting for a human to decide
export function isHeld(row: Order) {
  return row.status === "authorized" && row.review_state === "needs_review" && !row.error
}

// paid and captured here, without going through Check (a manual test buy, or Check is off)
function isPaidDirectly(row: Order) {
  return row.check_order_id === null && row.status === "captured"
}

// the row's color says where the money is: amber held, green captured, gray voided, and no
// tint for an order that was paid directly. the classes are in index.css
const ROW_CLASS_RULES: RowClassRules<OrderRow> = {
  "row-held": (params) => !!params.data && isHeld(params.data),
  "row-captured": (params) => !!params.data && params.data.status === "captured" && !isPaidDirectly(params.data),
  "row-voided": (params) => params.data?.status === "voided",
  "row-direct": (params) => !!params.data && isPaidDirectly(params.data),
}

// which cell of the order a field Check flagged shows up in
const FLAGGED_CELL: Record<string, string> = {
  price: "total",
  unit_price: "total",
  total: "total",
  max_price: "total",
  shipping: "total",
  currency: "total",
  merchant: "store",
  store: "store",
  quantity: "quantity",
}

function isFlagged(row: OrderRow | undefined, colId: string) {
  if (!row || row.check_verdict === "match") return false
  for (const field of row.check_mismatched_fields) {
    // anything about the item itself (size, color, model, a substitution) lands on the item
    if ((FLAGGED_CELL[field] || "description") === colId) return true
  }
  return false
}

interface GridContext {
  overlay: OverlayStore
  find: FindStore
  // agent orders go through Check, so "paid directly" means something
  checkOn: boolean
  reviewLinks: boolean
  openReview: (orderId: number) => void
  // scroll to another order's row and light it up
  goToOrder: (orderId: number) => void
  // Check's number for one of our orders, like "#45", by our own id. the grid shows Check's
  // numbers everywhere so they match the Check dashboard
  numberOf: (orderId: number) => string
}

type CellProps = CustomCellRendererProps<OrderRow, unknown, GridContext>

function FlagMark({ row, colId }: { row: OrderRow | undefined; colId: string }) {
  if (!isFlagged(row, colId)) return null
  // the tint on the cell is never the only signal
  return (
    <motion.span className="shrink-0 text-bad" role="img" aria-label="Check flagged this" initial={{ scale: 0, rotate: -45 }} animate={{ scale: 1, rotate: 0 }} transition={POP}>
      <EqualNot className="size-3.5" strokeWidth={2.5} />
    </motion.span>
  )
}

function ValueCell(props: CellProps) {
  const colId = props.column?.getColId() || ""
  const text = props.valueFormatted ?? (props.value === null || props.value === undefined ? "" : String(props.value))
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <FlagMark row={props.data} colId={colId} />
      <span className="truncate">
        <FindText text={text} rowId={props.node.id || ""} colId={colId} store={props.context.find} />
      </span>
    </span>
  )
}

// "the fix for order 3" under the item of an order Check placed for an accepted fix
function ItemCell({ data, node, context }: CellProps) {
  if (!data) return null
  const name = (
    <span className="truncate">
      <FindText text={data.description} rowId={node.id || ""} colId="description" store={context.find} />
    </span>
  )
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <FlagMark row={data} colId="description" />
      {data.replaces_order_id === null ? (
        name
      ) : (
        <span className="flex min-w-0 flex-col justify-center leading-tight">
          {name}
          <span className="truncate text-xs text-muted-foreground">The fix for order {context.numberOf(data.replaces_order_id)}</span>
        </span>
      )}
    </span>
  )
}

function ByCell({ value }: CellProps) {
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

function statusKey(data: OrderRow) {
  return data.status + "/" + (data.review_state || "") + "/" + (data.replaced_by_order_id ?? "")
}

function StatusBody({ data, context }: { data: OrderRow; context: GridContext }) {
  // the human accepted Check's suggested fix: this order was voided and a new one placed.
  // the old row says so and points at the new one
  if (data.status === "voided" && data.replaced_by_order_id !== null) {
    const newId = data.replaced_by_order_id
    return (
      <span className="flex min-w-0 items-center gap-2">
        <Pill tone="muted">
          <Undo2 className="size-3.5" /> Fixed
        </Pill>
        <button
          type="button"
          onClick={() => context.goToOrder(newId)}
          aria-label={"Go to the new order, " + context.numberOf(newId)}
          className="inline-flex h-11 items-center gap-1 text-xs font-medium whitespace-nowrap text-primary hover:underline"
        >
          New order {context.numberOf(newId)} <ArrowRight className="size-3" />
        </button>
      </span>
    )
  }
  if (isPaidDirectly(data) && context.checkOn) {
    // neutral on purpose: nothing was held or checked, it was simply paid
    return (
      <Pill tone="muted">
        <Check className="size-3.5" strokeWidth={3} /> Paid directly
      </Pill>
    )
  }
  if (data.status === "captured") {
    return (
      <Pill tone="ok">
        <Check className="size-3.5" strokeWidth={3} /> Captured
      </Pill>
    )
  }
  // the two states only an order that went through Check can be in
  if (isHeld(data)) {
    // why, in two or three words: "Held: wrong size". the full sentence is in the Reason column
    return (
      <Pill tone="warn">
        <Hourglass className="size-3.5" /> {heldLabel(data.check_mismatched_fields, data.check_verdict)}
      </Pill>
    )
  }
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

function StatusCell({ data, context }: CellProps) {
  if (!data) return null
  // the chip springs in again each time the order moves to a new state
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span key={statusKey(data)} className="flex h-full min-w-0 items-center" initial={{ scale: 0.7, opacity: 0, y: 6 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={POP}>
        <StatusBody data={data} context={context} />
      </motion.span>
    </AnimatePresence>
  )
}

// what Check concluded about the order, or a dash for an order that never went through it
function VerdictCell({ data }: CellProps) {
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

function ReviewCell({ data, context }: CellProps) {
  if (!data || !data.review_state) return <span className="text-muted-foreground/60">-</span>
  if (data.review_action === "accept_fix") return <Pill tone="muted">Fix accepted</Pill>
  if (data.review_state !== "needs_review") {
    const tone = data.review_state === "rejected" ? "muted" : "ok"
    return <Pill tone={tone}>{REVIEW_LABELS[data.review_state] || data.review_state}</Pill>
  }
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Pill tone="warn">Needs review</Pill>
      {context.reviewLinks && (
        // opens the drawer. it never decides anything from here, the confirm page does, and
        // the review link is only asked for once the drawer is open.
        // 44px tall so it's a fair target on a touch screen
        <motion.button
          whileTap={{ scale: 0.94 }}
          transition={POP}
          type="button"
          onClick={() => context.openReview(data.id)}
          aria-label={"Review order " + (checkNumber(data) ?? "")}
          className="inline-flex h-11 items-center rounded-lg bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:opacity-90"
        >
          Review
        </motion.button>
      )}
    </span>
  )
}

function DecideTimeCell({ data }: CellProps) {
  if (!data || data.decision_ms === null) return <span className="text-muted-foreground/60">-</span>
  const fast = data.review_action === "approve" && data.decision_ms > 0 && data.decision_ms < FAST_MS
  return (
    <span className="flex items-center gap-2">
      <span className="tabular-nums">{decisionTime(data.decision_ms)}</span>
      {fast && (
        <motion.span
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ ...POP, delay: 0.15 }}
          className="inline-flex h-5 items-center gap-1 rounded-md bg-warn-soft px-1.5 text-[11px] leading-none font-medium whitespace-nowrap text-warn"
          title={"Approved in under " + FAST_MS / 1000 + "s, too fast to have been read"}
        >
          <Zap className="size-3" aria-hidden /> Fast approval
        </motion.span>
      )}
    </span>
  )
}

const flaggedRules = {
  "cell-mismatch": (params: CellClassParams<OrderRow>) => isFlagged(params.data, params.column.getColId()),
}

const findable = { findable: true }

const DEFAULT_COL_DEF: ColDef<OrderRow> = { sortable: true, resizable: true }

// the grid starts empty, rows then arrive as transactions
const NO_ROWS: OrderRow[] = []

export function OrdersGrid({
  rows,
  loaded,
  checkOn,
  checkStats,
  heldRates,
  reviewLinks,
  onOpenReview,
  onGoToAgent,
}: {
  rows: OrderRow[]
  // false until the first answer from the API, for the loading overlay
  loaded: boolean
  // agent orders go through Check, so the grid shows what it decided
  checkOn: boolean
  // Check's rubber-stamp watch. null when Check or its merchant key isn't set
  checkStats: CheckStats | null
  // per agent, how often Check held its orders. empty hides the line
  heldRates: AgentHeldRate[]
  reviewLinks: boolean
  onOpenReview: (orderId: number) => void
  onGoToAgent: () => void
}) {
  const layout = useGridLayout("orders")
  const wrapper = useRef<HTMLDivElement>(null)
  const wide = useWideScreen()
  const [grouped, setGrouped] = useState(true)

  // orders waiting for a human are pinned to the top, everything else is the list
  const pinned = useMemo(() => rows.filter(isHeld), [rows])
  const body = useMemo(() => rows.filter((row) => !isHeld(row)), [rows])
  const { gridApi, onGridReady } = useGridRows(body, (row) => String(row.id))
  const find = useGridFind(gridApi)

  // from a fixed order to the order that replaced it
  const goToOrder = useCallback(
    (orderId: number) => {
      if (!gridApi || gridApi.isDestroyed()) return
      const node = gridApi.getRowNode(String(orderId))
      if (!node) return
      gridApi.ensureNodeVisible(node, "middle")
      flashGridRow(gridApi, wrapper.current, String(orderId), "new")
    },
    [gridApi]
  )

  const overlay = useMemo(
    () =>
      createOverlayStore({
        loading: { title: "Loading orders..." },
        empty: { title: "No orders yet" },
        noMatch: { title: "No order matches that search", actionLabel: "Clear the search", onAction: () => {} },
      }),
    []
  )
  const { setTerm } = find
  // right after Reset demo our own table is empty while Check holds the seed orders. say that,
  // with Check's real count, instead of a bare "No orders yet" that reads like the reset broke
  const checkTotal = checkOn && checkStats ? checkStats.check_total_orders : null
  useEffect(() => {
    let empty
    if (checkTotal !== null && checkTotal !== undefined && checkTotal > 0) {
      empty = {
        icon: <ReceiptText />,
        title: "No agent purchases yet",
        hint:
          "Check holds " +
          checkTotal +
          (checkTotal === 1 ? " earlier order" : " earlier orders") +
          " from the demo agents.",
        actionLabel: "Open the Check dashboard",
        onAction: () => {
          window.location.href = CHECK_URL + "/dashboard"
        },
      }
    } else {
      empty = {
        icon: <ReceiptText />,
        title: "No orders yet",
        hint: "Ask the shopping agent to buy something from a connected store, or use Test buy on a verified item.",
        actionLabel: "Send an agent shopping",
        onAction: onGoToAgent,
      }
    }
    overlay.set({
      loading: { title: "Loading orders..." },
      empty,
      noMatch: { title: "No order matches that search", actionLabel: "Clear the search", onAction: () => setTerm("") },
    })
  }, [overlay, onGoToAgent, setTerm, checkTotal])

  // our id to Check's number, for the rows that point at each other (an accepted fix)
  const numberOf = useCallback(
    (orderId: number) => {
      for (const row of rows) {
        if (row.id === orderId) return checkNumber(row) ?? ""
      }
      return ""
    },
    [rows]
  )

  const context = useMemo<GridContext>(
    () => ({ overlay, find: find.store, checkOn, reviewLinks, openReview: onOpenReview, goToOrder, numberOf }),
    [overlay, find.store, checkOn, reviewLinks, onOpenReview, goToOrder, numberOf]
  )

  useEffect(() => {
    if (gridApi && !gridApi.isDestroyed()) gridApi.setGridOption("quickFilterText", find.term)
  }, [gridApi, find.term])

  // ---- what changed since the last poll: flash it, and let an unpinned row travel down ----

  const before = useRef<Map<number, { key: string; held: boolean }> | null>(null)
  const flashed = useRef<Set<number>>(new Set())
  // where each pinned row sits on screen, measured while it is still pinned
  const pinnedTops = useRef<Map<number, number>>(new Map())
  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    const was = before.current
    const now = new Map<number, { key: string; held: boolean }>()
    for (const row of rows) now.set(row.id, { key: statusKey(row) + "/" + (row.decision_ms ?? ""), held: isHeld(row) })
    before.current = now

    for (const row of rows) {
      const old = was?.get(row.id)
      if (!old) {
        // a new order lights up its row. orders already there on first load don't
        if (flashed.current.has(row.id)) continue
        flashed.current.add(row.id)
        if (row.seen_at !== 0 && Date.now() - row.seen_at < 1500 && !isHeld(row)) {
          flashGridRow(gridApi, wrapper.current, String(row.id), row.status === "captured" ? "ok" : "bad")
        }
        continue
      }
      if (old.key === now.get(row.id)!.key) continue
      const tone = row.status === "captured" ? "ok" : row.status === "voided" || row.status === "failed" ? "bad" : "new"
      flashGridCells(gridApi, wrapper.current, String(row.id), ["status", "review_state", "decision_ms"], tone)

      const from = pinnedTops.current.get(row.id)
      if (!old.held || isHeld(row) || from === undefined) continue
      const node = gridApi.getRowNode(String(row.id))
      if (node) gridApi.ensureNodeVisible(node)
      // two frames: one for the grid to draw the row in the list, one to measure it
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          const container = wrapper.current
          if (!container || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
          const cells: HTMLElement[] = []
          let top: number | null = null
          for (const element of container.querySelectorAll<HTMLElement>('.ag-row[row-id="' + row.id + '"]')) {
            if (top === null) top = element.getBoundingClientRect().top
            for (const cell of element.querySelectorAll<HTMLElement>(".ag-cell")) cells.push(cell)
          }
          if (top === null || cells.length === 0) return
          animate(cells, { y: [from - top, 0] }, { duration: 0.55, ease: [0.2, 0, 0, 1] })
        })
      )
    }

    // measure the rows that are pinned now, for the next time one of them leaves
    requestAnimationFrame(() => {
      const container = wrapper.current
      if (!container) return
      pinnedTops.current = new Map()
      for (const row of rows) {
        if (!isHeld(row)) continue
        const element = container.querySelector<HTMLElement>('.ag-row[row-id="' + row.id + '"]')
        if (element) pinnedTops.current.set(row.id, element.getBoundingClientRect().top)
      }
    })
  }, [gridApi, rows])

  // ---- columns ----

  const columnDefs = useMemo<(ColDef<OrderRow> | ColGroupDef<OrderRow>)[]>(
    () => [
      {
        headerName: "Order",
        headerClass: "group-order",
        marryChildren: true,
        children: [
          {
            // Check's number, the same one the Check dashboard shows. a dash for a test buy that
            // was paid directly and never went through Check
            headerName: "#",
            colId: "check_number",
            valueGetter: (params) => params.data?.check_order_id ?? null,
            valueFormatter: (params) => (params.value === null || params.value === undefined ? "-" : "#" + params.value),
            cellClass: "tabular-nums text-muted-foreground",
            width: 76,
            hide: !checkOn,
          },
          {
            headerName: "Store",
            colId: "store",
            valueGetter: (params) => params.data?.store_name || "Store " + params.data?.store_id,
            // one tall cell per store when grouping is on (cell spanning, a Community feature)
            spanRows: grouped,
            sort: grouped ? "asc" : null,
            sortIndex: 0,
            context: findable,
            cellRenderer: ValueCell,
            cellClassRules: flaggedRules,
            cellClass: grouped ? "font-medium !items-start !pt-3 bg-card" : "font-medium",
            width: 190,
            filter: true,
          },
          { headerName: "Item", field: "description", colId: "description", context: findable, cellRenderer: ItemCell, cellClassRules: flaggedRules, width: 240, filter: true },
          { headerName: "Qty", field: "quantity", colId: "quantity", width: 78, cellRenderer: ValueCell, cellClassRules: flaggedRules, cellClass: "tabular-nums" },
          {
            headerName: "Total",
            field: "total",
            colId: "total",
            width: 116,
            cellRenderer: ValueCell,
            cellClassRules: flaggedRules,
            cellClass: "font-mono tabular-nums",
            valueFormatter: (params) => (params.data ? money(params.value, params.data.currency) : ""),
            comparator: (a, b) => Number(a) - Number(b),
          },
          { headerName: "Bought by", field: "created_by", width: 122, cellRenderer: ByCell },
        ],
      },
      {
        // what Check made of it. only when agent orders go through Check
        headerName: "Check",
        headerClass: "group-check",
        marryChildren: true,
        children: [
          // right after the money, so "Held: wrong size" and "Fixed" are on screen without scrolling
          { headerName: "Status", field: "status", colId: "status", cellRenderer: StatusCell, width: checkOn ? 230 : 150, filter: true },
          { headerName: "Verdict", field: "check_verdict", cellRenderer: VerdictCell, width: 124, hide: !checkOn },
          {
            headerName: "Reason",
            field: "check_reason",
            width: 280,
            hide: !checkOn,
            context: findable,
            cellRenderer: FindCell,
            tooltipField: "check_reason",
            cellClass: "text-muted-foreground",
            filter: true,
          },
        ],
      },
      {
        headerName: "Decision",
        headerClass: "group-decision",
        marryChildren: true,
        children: [
          {
            headerName: "Time to decide",
            field: "decision_ms",
            colId: "decision_ms",
            width: 196,
            hide: !checkOn,
            cellRenderer: DecideTimeCell,
            headerTooltip: "From the confirm page opening to the tap, on Check's own clock",
          },
          {
            headerName: "Placed",
            field: "created_at",
            width: 118,
            sort: "desc",
            sortIndex: 1,
            valueFormatter: (params) => clockTime(params.value),
            cellClass: "text-muted-foreground tabular-nums",
          },
        ],
      },
      {
        headerName: "PayPal",
        headerClass: "group-paypal",
        marryChildren: true,
        children: [
          { headerName: "PayPal order", field: "paypal_order_id", width: 180, cellRenderer: (params: CellProps) => <CopyId value={params.data?.paypal_order_id || null} /> },
          { headerName: "Capture", field: "capture_id", width: 180, cellRenderer: (params: CellProps) => <CopyId value={params.data?.capture_id || null} /> },
        ],
      },
      {
        headerName: "Review",
        field: "review_state",
        colId: "review_state",
        cellRenderer: ReviewCell,
        width: 236,
        hide: !checkOn,
        sortable: false,
        suppressMovable: true,
        // stays in view while the other columns scroll, so the Review button is never off screen.
        // not on a narrow screen, where a pinned column would leave no room for the rest
        pinned: wide ? "right" : null,
      },
    ],
    [grouped, checkOn, wide]
  )

  // ---- the strip above the grid ----

  let fastApprovals = 0
  for (const row of rows) {
    if (row.review_action === "approve" && row.decision_ms !== null && row.decision_ms > 0 && row.decision_ms < FAST_MS) fastApprovals += 1
  }
  // another fast approval makes the strip jolt, so it is noticed the moment it happens
  const strip = useRef<HTMLDivElement>(null)
  const lastFast = useRef<number | null>(null)
  useEffect(() => {
    const grew = lastFast.current !== null && fastApprovals > lastFast.current
    lastFast.current = fastApprovals
    if (!grew || !strip.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    animate(strip.current, { scale: [1, 1.07, 1], rotate: [0, -1.5, 1.5, 0] }, { duration: 0.5, ease: "easeOut" })
  }, [fastApprovals])

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2">
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
                {find.count === 0 ? (
                  "No matches"
                ) : (
                  <>
                    <CountRoll value={find.current} /> of {find.count}
                  </>
                )}
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

        {checkOn && (
          // approvals too fast to have been read
          <motion.div
            ref={strip}
            layout
            role="status"
            aria-label={"Rubber-stamp risk: " + fastApprovals + (fastApprovals === 1 ? " approval" : " approvals") + " under " + FAST_MS / 1000 + " seconds"}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px]",
              fastApprovals > 0 ? "bg-warn-soft font-medium text-warn" : "bg-muted text-muted-foreground"
            )}
            title="An approval this fast was almost certainly not read."
          >
            <Zap className="size-3.5" aria-hidden />
            <span>Rubber-stamp risk:</span> <CountRoll value={fastApprovals} />
            <span>
              {fastApprovals === 1 ? "approval" : "approvals"} under {FAST_MS / 1000}s
            </span>
          </motion.div>
        )}

        {checkOn && checkStats && (
          // whether Check's rubber-stamp watch is on right now. the agent never sees this
          <span
            role="status"
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px]",
              checkStats.rubber_stamp_active ? "bg-warn-soft font-medium text-warn" : "bg-muted text-muted-foreground"
            )}
            title={
              checkStats.rubber_stamp_active
                ? checkStats.fast_streak + " fast approvals in a row, so Check holds fewer orders but makes each one count"
                : "Approvals have been slow enough to have been read"
            }
          >
            <span className={cn("size-1.5 rounded-full", checkStats.rubber_stamp_active ? "bg-warn" : "bg-muted-foreground/50")} aria-hidden />
            {checkStats.rubber_stamp_active ? "Sharp mode on: asking less, but sharper" : "Sharp mode off"}
          </span>
        )}

        {checkOn && heldRates.length > 0 && (
          <span className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground" title="Orders Check held for the buyer, out of every order it checked">
            {heldRates.map((rate) => (
              <span key={rate.created_by} className="tabular-nums">
                {rate.label}: {rate.held} of {rate.total} held ({rate.held_pct}%)
              </span>
            ))}
          </span>
        )}

        <AnimatePresence initial={false}>
          {pinned.length > 0 && (
            <motion.span key="pinned" layout initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Hourglass className="size-3.5 text-warn" aria-hidden /> <CountRoll value={pinned.length} /> pinned until decided
            </motion.span>
          )}
        </AnimatePresence>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
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
          pinnedTopRowData={pinned}
          columnDefs={columnDefs}
          defaultColDef={DEFAULT_COL_DEF}
          rowClassRules={ROW_CLASS_RULES}
          getRowId={(params: GetRowIdParams<OrderRow>) => String(params.data.id)}
          // taller than the theme's 44 so the 44px Review button has air around it
          rowHeight={52}
          groupHeaderHeight={34}
          enableCellSpan
          context={context}
          initialState={layout.initialState}
          onStateUpdated={layout.onStateUpdated}
          loading={!loaded}
          overlayComponent={GridOverlay}
          tooltipShowDelay={300}
          onGridReady={onGridReady}
          animateRows
        />
      </div>
    </div>
  )
}
