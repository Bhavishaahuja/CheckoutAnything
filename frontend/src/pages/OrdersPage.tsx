import type {
  ColDef,
  GetRowIdParams,
  ICellRendererParams,
  IsFullWidthRowParams,
  RowHeightParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getOrders } from '../api'
import { CreatedByCell, MonoCell, OrderStatusCell } from '../components/cells'
import { gridTheme } from '../gridTheme'
import type { Order } from '../types'

// Grouping by store is done with Community features only: the rows are sorted by store and
// each store gets a full-width header row. AG Grid's built-in row grouping is Enterprise.
interface GroupRow {
  kind: 'group'
  key: string
  storeName: string
  count: number
  captured: number
  total: number
  currency: string
}

interface OrderRow extends Order {
  kind: 'order'
  key: string
}

type Row = GroupRow | OrderRow

function buildRows(orders: Order[], grouped: boolean): Row[] {
  if (!grouped) {
    return orders.map((order) => ({ ...order, kind: 'order', key: 'order-' + order.id }))
  }
  // keep the stores in the order of their newest order
  const byStore = new Map<number, Order[]>()
  for (const order of orders) {
    const list = byStore.get(order.store_id) ?? []
    list.push(order)
    byStore.set(order.store_id, list)
  }
  const rows: Row[] = []
  for (const [storeId, list] of byStore) {
    let total = 0
    let captured = 0
    for (const order of list) {
      if (order.status === 'captured') {
        captured += 1
        total += Number(order.total)
      }
    }
    rows.push({
      kind: 'group',
      key: 'group-' + storeId,
      storeName: list[0].store_name ?? 'Store ' + storeId,
      count: list.length,
      captured,
      total,
      currency: list[0].currency,
    })
    for (const order of list) {
      rows.push({ ...order, kind: 'order', key: 'order-' + order.id })
    }
  }
  return rows
}

function GroupHeader(params: ICellRendererParams<Row>) {
  const row = params.data
  if (!row || row.kind !== 'group') return null
  return (
    <div className="grouprow">
      <span className="grouprow__name">{row.storeName}</span>
      <span className="faint">
        {row.count} {row.count === 1 ? 'order' : 'orders'} · {row.captured} captured ·{' '}
        <span className="mono">{row.total.toFixed(2)} {row.currency}</span>
      </span>
    </div>
  )
}

function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  return new Date(value).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export default function OrdersPage({ visible }: { visible: boolean }) {
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState<string | null>(null)
  const [grouped, setGrouped] = useState(true)
  const [search, setSearch] = useState('')

  const load = useCallback(() => {
    getOrders()
      .then((loaded) => {
        setOrders(loaded)
        setError(null)
      })
      .catch((failure: Error) => setError(failure.message))
  }, [])

  // only poll while someone is looking
  useEffect(() => {
    if (!visible) return
    load()
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [visible, load])

  const rows = useMemo(() => buildRows(orders, grouped), [orders, grouped])

  const columns = useMemo<ColDef<Row>[]>(
    () => [
      { field: 'store_name' as never, headerName: 'Store', width: 190, hide: grouped },
      { field: 'description' as never, headerName: 'Item', flex: 2, minWidth: 200 },
      { field: 'quantity' as never, headerName: 'Qty', width: 80, type: 'rightAligned' },
      {
        field: 'total' as never,
        headerName: 'Total',
        width: 120,
        type: 'rightAligned',
        cellClass: 'mono',
        valueFormatter: (params) => {
          const row = params.data
          return row && row.kind === 'order' ? row.total + ' ' + row.currency : ''
        },
      },
      { field: 'paypal_order_id' as never, headerName: 'PayPal order id', flex: 1, minWidth: 180, cellRenderer: MonoCell },
      { field: 'capture_id' as never, headerName: 'Capture id', flex: 1, minWidth: 180, cellRenderer: MonoCell },
      { field: 'created_by' as never, headerName: 'Created by', width: 120, cellRenderer: CreatedByCell },
      { field: 'status' as never, headerName: 'Status', width: 130, cellRenderer: OrderStatusCell },
      {
        field: 'created_at' as never,
        headerName: 'Time',
        width: 170,
        valueFormatter: (params) => formatTime(params.value as string | null),
      },
    ],
    [grouped],
  )

  // sorting would pull orders away from their store's header row, so it's off while grouped
  const defaultColumn = useMemo<ColDef>(
    () => ({ sortable: !grouped, resizable: true, suppressMovable: true }),
    [grouped],
  )

  const getRowId = useCallback((params: GetRowIdParams<Row>) => params.data.key, [])
  const isFullWidthRow = useCallback(
    (params: IsFullWidthRowParams<Row>) => params.rowNode.data?.kind === 'group',
    [],
  )
  const getRowHeight = useCallback(
    (params: RowHeightParams<Row>) => (params.data?.kind === 'group' ? 40 : 44),
    [],
  )

  const capturedCount = orders.filter((order) => order.status === 'captured').length

  return (
    <div className="orders">
      <div className="orders__head">
        <div>
          <h1>Orders</h1>
          <p className="hero__sub">
            Every purchase made through a connected store. {capturedCount} captured of {orders.length}.
          </p>
        </div>
        <div className="orders__tools">
          <input
            className="input input--small"
            placeholder="Filter orders"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Filter orders"
            disabled={grouped}
            title={grouped ? 'Turn off grouping to filter' : undefined}
          />
          <label className="toggle">
            <input type="checkbox" checked={grouped} onChange={(event) => setGrouped(event.target.checked)} />
            <span>Group by store</span>
          </label>
        </div>
      </div>
      {error && <div className="banner banner--bad banner--inline">{error}</div>}
      <div className="grid-wrap grid-wrap--tall">
        <AgGridReact<Row>
          theme={gridTheme}
          columnDefs={columns}
          defaultColDef={defaultColumn}
          rowData={rows}
          getRowId={getRowId}
          isFullWidthRow={isFullWidthRow}
          fullWidthCellRenderer={GroupHeader}
          getRowHeight={getRowHeight}
          quickFilterText={grouped ? '' : search}
          animateRows
          suppressCellFocus
          overlayNoRowsTemplate="No orders yet. Ask the agent to buy something."
        />
      </div>
    </div>
  )
}
