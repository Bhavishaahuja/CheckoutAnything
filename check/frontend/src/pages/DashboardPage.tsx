import {
  CellStyleModule,
  ClientSideRowModelModule,
  ExternalFilterModule,
  HighlightChangesModule,
  ModuleRegistry,
  QuickFilterModule,
  RowApiModule,
  RowSelectionModule,
  RowStyleModule,
  ValidationModule,
  type ColDef,
  type IRowNode,
  type RowClassParams,
  type RowClassRules,
  type RowClickedEvent,
  type RowDataUpdatedEvent,
} from 'ag-grid-community'
import { LicenseManager, RowGroupingModule } from 'ag-grid-enterprise'
import { AgGridReact } from 'ag-grid-react'
import { LoaderCircle, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card, ErrorNote, Switch } from '@/components/bits'
import { calmTheme } from '@/lib/gridTheme'
import { cn } from '@/lib/utils'
import { DEMO_RESET_EVENT, getStats, listOrders } from '../api'
import { OrderPanel } from '../components/OrderPanel'
import { StatsTiles } from '../components/StatsTiles'
import {
  DecideTimeCell,
  DecisionCell,
  HeldRateCell,
  OrderCell,
  ROW_LINK_ATTRIBUTE,
  ReasonCell,
  RiskCell,
  StatusCell,
  TotalCell,
  type OrderGridContext,
} from '../components/orderCells'
import { buyerName, formatTime, summarizeItems } from '../lib/format'
import { DECISION_LABELS, decisionKind, decisionMs, displayStatus, heldRateAgg, heldRateValue, statusLabel } from '../lib/orderState'
import { usePolling } from '../lib/usePolling'
import type { Order } from '../types'

// only the grid features we use, so the bundle stays small. ValidationModule only runs in dev
// and warns in the console when a grid option needs a module that isn't registered here
const gridModules = [
  ClientSideRowModelModule,
  QuickFilterModule,
  ExternalFilterModule,
  // forEachNode and redrawRows, for the flash on rows that just changed
  RowApiModule,
  RowSelectionModule,
  RowStyleModule,
  CellStyleModule,
  // the flash on a cell whose value changed between two polls
  HighlightChangesModule,
  // Enterprise: group by agent, and the per-agent held rate
  RowGroupingModule,
]
if (import.meta.env.DEV) {
  gridModules.push(ValidationModule)
}
ModuleRegistry.registerModules(gridModules)

// the trial key comes from the build env (Render sets it). without one the grid still groups,
// it just shows AG Grid's watermark
const agGridLicenseKey = import.meta.env.VITE_AG_GRID_LICENSE_KEY
if (agGridLicenseKey) {
  LicenseManager.setLicenseKey(agGridLicenseKey)
}

// what a group row's name is when an old order has no agent on it
const UNKNOWN_AGENT = 'Unknown agent'

// the row's color says where the money is, the same four meanings as the Checkout Anything
// Orders grid: amber on hold for a human, green captured, gray voided (a fixed order is a voided
// one). everything here went through Check, so there is no "paid directly" row to leave plain.
// the classes are in legacy.css, with the same mixes as the Checkout Anything app's
const ROW_CLASS_RULES: RowClassRules<Order> = {
  'row--needs-review': (params) => params.data?.review_state === 'needs_review',
  'row--held': (params) => params.data?.status === 'authorized' && params.data?.review_state === 'needs_review',
  'row--captured': (params) => params.data?.status === 'captured',
  'row--voided': (params) => params.data?.status === 'voided',
}

type Filter = 'all' | 'needs_review' | 'auto' | 'human'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'needs_review', label: 'Needs review' },
  { id: 'auto', label: 'Auto-captured' },
  { id: 'human', label: 'Human decided' },
]

function matchesFilter(order: Order, filter: Filter): boolean {
  if (filter === 'needs_review') {
    return order.review_state === 'needs_review'
  }
  if (filter === 'auto') {
    return order.review_state === 'auto_approved'
  }
  if (filter === 'human') {
    return order.review_state === 'approved' || order.review_state === 'rejected'
  }
  return true
}

// how urgent a status is, so sorting the Status column puts work-to-do on top
const STATUS_ORDER = ['needs_review', 'created', 'authorized', 'failed', 'fixed', 'voided', 'captured']

// below this the grid only has room for about three columns, so it keeps the ones a merchant on a
// phone actually needs: what was ordered, whether money is held, and how much
const NARROW_SCREEN = '(max-width: 640px)'

function useNarrowScreen(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW_SCREEN).matches)
  useEffect(() => {
    const query = window.matchMedia(NARROW_SCREEN)
    const update = () => setNarrow(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return narrow
}

// stable loader identity so the poll doesn't restart on every render
const loadOrders = () => listOrders()
const loadStats = () => getStats()

// how often the grid asks for fresh orders. fast enough that an approve on the phone shows up on the
// laptop while you're still looking, slow enough to be nothing for the API
const POLL_MS = 4000

// how long a changed row keeps its flash class. matches the row-flash animation in index.css
const FLASH_MS = 2400

// Merchant view: every agent order, what the check said, and what the human did about it.
export function DashboardPage() {
  const { state: orders, stale, refresh: refreshOrders } = usePolling(loadOrders, POLL_MS)
  const { state: stats, refresh: refreshStats } = usePolling(loadStats, POLL_MS)
  const gridRef = useRef<AgGridReact<Order>>(null)
  // each row's status as of the last poll, so we can tell which rows just changed.
  // null until the first load, which shouldn't flash anything
  const lastStatuses = useRef<Map<number, string> | null>(null)
  // rows flashing right now: order id to the status it flashes as
  const flashing = useRef<Map<number, string>>(new Map())
  const flashTimers = useRef<ReturnType<typeof setTimeout>[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const narrow = useNarrowScreen()
  const [groupByAgent, setGroupByAgent] = useState(false)

  const columnDefs = useMemo<ColDef<Order>[]>(() => {
    const timeColumn: ColDef<Order> = {
      headerName: 'Time',
      field: 'created_at',
      valueFormatter: (params) => (params.value ? formatTime(params.value) : ''),
      // still sorts newest first when hidden on a phone
      sort: 'desc',
      hide: narrow,
      width: 150,
      cellClass: 'muted tabular-nums',
    }
    const orderColumn: ColDef<Order> = {
      headerName: 'Order',
      colId: 'order',
      // what quick search and sorting see: the item, the buyer and the order number
      valueGetter: (params) =>
        params.data ? summarizeItems(params.data.items) + ' ' + buyerName(params.data.mandate.buyer_label) + ' #' + params.data.id : '',
      cellRenderer: OrderCell,
      minWidth: narrow ? 120 : 200,
      flex: 1.2,
    }
    const totalColumn: ColDef<Order> = {
      headerName: 'Total',
      field: 'total',
      valueGetter: (params) => (params.data ? Number(params.data.total) : null),
      cellRenderer: TotalCell,
      type: 'rightAligned',
      width: narrow ? 90 : 100,
    }
    const statusColumn: ColDef<Order> = {
      headerName: 'Status',
      colId: 'status',
      valueGetter: (params) => (params.data ? displayStatus(params.data) : ''),
      // quick search finds "wrong size" too
      getQuickFilterText: (params) => (params.data ? (statusLabel(params.data) ?? String(params.value)) : ''),
      comparator: (a: string, b: string) => STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b),
      cellRenderer: StatusCell,
      // wide enough for the longest chip, "Waiting on buyer", or "Fixed" with its link to the
      // new order
      width: narrow ? 170 : 215,
    }

    // on a phone, status comes right after the order so you can see what's held without scrolling
    let leadColumns = [timeColumn, orderColumn, totalColumn, statusColumn]
    if (narrow) {
      leadColumns = [timeColumn, orderColumn, statusColumn, totalColumn]
    }

    // grouped, this column becomes the group rows (AG Grid hides it and draws the auto group column).
    // ungrouped, it's a plain column so you can still see who placed each order
    const agentColumn: ColDef<Order> = {
      headerName: 'Agent',
      colId: 'agent',
      valueGetter: (params) => (params.data ? params.data.agent_name ?? UNKNOWN_AGENT : ''),
      rowGroup: groupByAgent,
      hide: groupByAgent || narrow,
      width: 130,
      cellClass: 'muted',
    }

    // the trust score: only filled in on group rows, see HeldRateCell
    const heldColumn: ColDef<Order> = {
      headerName: 'Held by Check',
      colId: 'held',
      // null for a fix's replacement order, which heldRateAgg then leaves out
      valueGetter: (params) => (params.data ? heldRateValue(params.data) : null),
      aggFunc: heldRateAgg,
      cellRenderer: HeldRateCell,
      hide: !groupByAgent,
      // sorting groups by it puts the least trusted agent on top
      comparator: (a, b) => {
        const rateA = a && typeof a === 'object' && a.total ? a.held / a.total : 0
        const rateB = b && typeof b === 'object' && b.total ? b.held / b.total : 0
        return rateA - rateB
      },
      width: 150,
    }

    return [
      heldColumn,
      ...leadColumns,
      agentColumn,
      {
        headerName: 'Risk',
        colId: 'risk',
        valueGetter: (params) => params.data?.intent_check?.risk_score ?? null,
        cellRenderer: RiskCell,
        width: 125,
      },
      {
        headerName: 'AI reason',
        colId: 'reason',
        valueGetter: (params) => params.data?.intent_check?.reason ?? '',
        cellRenderer: ReasonCell,
        minWidth: 240,
        flex: 2,
        sortable: false,
      },
      {
        headerName: 'Decision',
        colId: 'decision',
        valueGetter: (params) => (params.data ? DECISION_LABELS[decisionKind(params.data)] : ''),
        cellRenderer: DecisionCell,
        width: 150,
      },
      {
        headerName: 'Time to decide',
        colId: 'decision_ms',
        valueGetter: (params) => (params.data ? decisionMs(params.data) : null),
        cellRenderer: DecideTimeCell,
        width: 140,
      },
    ]
  }, [narrow, groupByAgent])

  // the column grouped rows show in: the agent's name and how many orders are under it
  const autoGroupColumnDef = useMemo<ColDef<Order>>(
    () => ({
      headerName: 'Agent',
      minWidth: 190,
    }),
    [],
  )

  const defaultColDef = useMemo<ColDef<Order>>(
    () => ({
      sortable: true,
      resizable: true,
      suppressMovable: true,
      // a poll hands the grid fresh rows. any cell whose value is different now flashes
      enableCellChangeFlash: true,
    }),
    [],
  )

  // the grid calls these on every filter pass, so they read the latest filter via deps
  const isExternalFilterPresent = useCallback(() => filter !== 'all', [filter])
  const doesExternalFilterPass = useCallback(
    (node: IRowNode<Order>) => (node.data ? matchesFilter(node.data, filter) : true),
    [filter],
  )

  useEffect(() => {
    // the grid doesn't watch our filter state, so tell it to re-run the external filter
    gridRef.current?.api?.onFilterChanged()
  }, [filter])

  const openOrder = useCallback((event: RowClickedEvent<Order>) => {
    // a click on the "New order #12" link inside a row is for that link, not for this row
    const target = event.event?.target
    if (target instanceof Element && target.closest('[' + ROW_LINK_ATTRIBUTE + ']')) {
      return
    }
    if (event.data) {
      setSelectedId(event.data.id)
    }
  }, [])

  // from a fixed order to the order that replaced it: scroll to the row, select it, open it
  const goToOrder = useCallback((orderId: number) => {
    const api = gridRef.current?.api
    const node = api?.getRowNode(String(orderId))
    if (api && node) {
      api.ensureNodeVisible(node, 'middle')
      node.setSelected(true)
    }
    setSelectedId(orderId)
  }, [])
  const gridContext = useMemo<OrderGridContext>(() => ({ goToOrder }), [goToOrder])

  useEffect(() => {
    // after a reset from the top bar, don't make the merchant wait for the next poll
    function handleReset() {
      refreshOrders()
      refreshStats()
    }
    window.addEventListener(DEMO_RESET_EVENT, handleReset)
    return () => window.removeEventListener(DEMO_RESET_EVENT, handleReset)
  }, [refreshOrders, refreshStats])

  useEffect(() => {
    const timers = flashTimers.current
    return () => {
      for (const timer of timers) {
        clearTimeout(timer)
      }
    }
  }, [])

  // runs after the grid has applied a poll. getRowId means it only touched rows that changed, so
  // selection and scroll stay put. here we just find which rows are new or changed status and
  // flash them in their new color: amber when a hold lands, green on capture, gray on void
  const onRowDataUpdated = useCallback((event: RowDataUpdatedEvent<Order>) => {
    const nextStatuses = new Map<number, string>()
    const changedNodes: IRowNode<Order>[] = []
    event.api.forEachNode((node) => {
      if (!node.data) {
        return
      }
      const status = displayStatus(node.data)
      nextStatuses.set(node.data.id, status)
      const before = lastStatuses.current?.get(node.data.id)
      if (lastStatuses.current !== null && before !== status) {
        flashing.current.set(node.data.id, status)
        changedNodes.push(node)
      }
    })
    lastStatuses.current = nextStatuses
    if (changedNodes.length === 0) {
      return
    }

    // redraw rebuilds the row element, so the CSS animation plays from the start
    event.api.redrawRows({ rowNodes: changedNodes })
    const timer = setTimeout(() => {
      for (const node of changedNodes) {
        if (node.data) {
          flashing.current.delete(node.data.id)
        }
      }
      // gridRef, not event.api: the grid may have been rebuilt since
      gridRef.current?.api?.redrawRows({ rowNodes: changedNodes })
    }, FLASH_MS)
    flashTimers.current.push(timer)
  }, [])

  const getRowClass = useCallback((params: RowClassParams<Order>) => {
    const status = params.data ? flashing.current.get(params.data.id) : undefined
    return status ? 'row--flash row--flash-' + status : undefined
  }, [])

  const closePanel = useCallback(() => {
    setSelectedId(null)
    gridRef.current?.api.deselectAll()
  }, [])

  const allOrders = orders.status === 'ready' ? orders.data : []
  const selectedOrder = allOrders.find((order) => order.id === selectedId) ?? null

  let needsReviewCount = 0
  for (const order of allOrders) {
    if (order.review_state === 'needs_review') {
      needsReviewCount += 1
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Agent orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Payments are held until the order matches what the shopper asked for.
        </p>
      </div>

      <StatsTiles stats={stats} />

      <Card className="overflow-hidden">
        {orders.status === 'loading' && (
          <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground" role="status">
            <LoaderCircle className="spin-slow size-4" aria-hidden /> Loading orders...
          </p>
        )}
        {orders.status === 'error' && (
          <div className="p-4">
            <ErrorNote>Couldn't load orders: {orders.error.message}</ErrorNote>
          </div>
        )}
        {orders.status === 'ready' && orders.data.length === 0 && (
          <p className="py-16 text-center text-sm text-muted-foreground">No agent orders yet.</p>
        )}
        {orders.status === 'ready' && orders.data.length > 0 && (
          <>
            <div className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2">
              <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="Filter orders">
                {FILTERS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={cn(
                      'flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium whitespace-nowrap transition-colors',
                      filter === option.id
                        ? 'bg-card text-foreground shadow-sm'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    aria-pressed={filter === option.id}
                    onClick={() => setFilter(option.id)}
                  >
                    {option.label}
                    {option.id === 'needs_review' && needsReviewCount > 0 && (
                      <span className="rounded-full bg-warn-soft px-1.5 text-[11px] leading-4 font-semibold text-warn tabular-nums">
                        {needsReviewCount}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
                  <span
                    className={cn('size-1.5 rounded-full', stale ? 'bg-warn' : 'animate-pulse bg-ok')}
                    aria-hidden="true"
                  />
                  {stale ? 'Reconnecting...' : 'Live'}
                </span>
                <Switch checked={groupByAgent} onChange={setGroupByAgent} label="Group by agent" />
                <div className="flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 focus-within:border-primary">
                  <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <input
                    type="search"
                    className="w-48 min-w-0 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground/70"
                    placeholder="Search item, buyer or order #"
                    aria-label="Search orders"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>
              </div>
            </div>
            <div className="grid-wrap">
              <AgGridReact<Order>
                ref={gridRef}
                theme={calmTheme}
                rowData={orders.data}
                columnDefs={columnDefs}
                defaultColDef={defaultColDef}
                getRowId={(params) => String(params.data.id)}
                context={gridContext}
                autoGroupColumnDef={autoGroupColumnDef}
                groupDefaultExpanded={-1}
                suppressAggFuncInHeader
                rowHeight={50}
                headerHeight={40}
                domLayout="autoHeight"
                quickFilterText={search}
                isExternalFilterPresent={isExternalFilterPresent}
                doesExternalFilterPass={doesExternalFilterPass}
                rowSelection={{ mode: 'singleRow', checkboxes: false, enableClickSelection: true }}
                rowClassRules={ROW_CLASS_RULES}
                animateRows
                getRowClass={getRowClass}
                onRowDataUpdated={onRowDataUpdated}
                onRowClicked={openOrder}
                onCellKeyDown={(event) => {
                  // Enter on a focused row opens it, same as a click
                  const keyEvent = event.event as KeyboardEvent | null | undefined
                  if (keyEvent?.key === 'Enter' && event.data) {
                    event.node.setSelected(true)
                    setSelectedId(event.data.id)
                  }
                }}
                overlayNoRowsTemplate='<span style="color: var(--muted-foreground); font-size: 13px">No orders match this filter.</span>'
              />
            </div>
          </>
        )}
      </Card>

      {selectedOrder && <OrderPanel order={selectedOrder} onClose={closePanel} onGoToOrder={goToOrder} />}
    </section>
  )
}
