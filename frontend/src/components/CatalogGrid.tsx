// The catalog on the Connect screen. Rows arrive one by one as items are checked, flip to
// verified or failed in place, and flash when they do.

import type { ColDef, GetRowIdParams, RowClassRules, RowClickedEvent } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import { useEffect, useMemo, useRef } from "react"

import { CheckMark, CopyId, RowStatusPill } from "@/components/bits"
import { money } from "@/lib/format"
import { flashGridRow } from "@/lib/gridFlash"
import { calmTheme } from "@/lib/gridTheme"
import type { CatalogRow } from "@/lib/types"
import { useGridRows } from "@/lib/useGridRows"
import { cn } from "@/lib/utils"

const rowClassRules: RowClassRules<CatalogRow> = {
  "row-dim": (params) => params.data?.status === "unavailable",
  "row-clickable": () => true,
}

function ItemCell({ data }: CustomCellRendererProps<CatalogRow>) {
  if (!data) return null
  const parts = []
  if (data.variant_count > 0) parts.push(data.variant_count + (data.variant_count === 1 ? " variant" : " variants"))
  if (data.add_on_count > 0) parts.push(data.add_on_count + (data.add_on_count === 1 ? " add-on" : " add-ons"))
  return (
    <div className="flex h-full min-w-0 flex-col justify-center leading-tight">
      <span className="truncate font-medium">{data.name}</span>
      {parts.length > 0 && <span className="truncate text-[11px] text-muted-foreground">{parts.join(", ")}</span>}
    </div>
  )
}

function RepairsCell({ data }: CustomCellRendererProps<CatalogRow>) {
  if (!data) return null
  if (data.repairs === 0) return <span className="text-muted-foreground/60">-</span>
  return (
    <span className="inline-flex items-center gap-1.5" title={data.repairs + " of 3 repairs used"}>
      {[1, 2, 3].map((slot) => (
        <span
          key={slot}
          className={cn(
            "size-1.5 rounded-full",
            slot <= data.repairs ? (data.status === "failed" ? "bg-bad" : "bg-warn") : "bg-border"
          )}
        />
      ))}
      <span className="ml-0.5 text-xs text-muted-foreground tabular-nums">{data.repairs}/3</span>
    </span>
  )
}

function StatusCell({ data }: CustomCellRendererProps<CatalogRow>) {
  if (!data) return null
  const showReason = data.reason && data.status !== "verified"
  return (
    <div className="flex h-full min-w-0 items-center gap-2">
      <RowStatusPill status={data.status} />
      {showReason && (
        <span className="truncate text-xs text-muted-foreground" title={data.reason || ""}>
          {data.reason}
        </span>
      )}
    </div>
  )
}

const centered = "flex items-center justify-center"

export function CatalogGrid({
  rows,
  selectedItemId,
  onPickItem,
}: {
  rows: CatalogRow[]
  selectedItemId: string | null
  onPickItem: (itemId: string) => void
}) {
  const { gridApi, onGridReady } = useGridRows(rows, (row) => row.item_id)
  const wrapper = useRef<HTMLDivElement>(null)
  // when each row last flashed, so a row flashes once per change
  const flashed = useRef<Map<string, number>>(new Map())

  // AG Grid flash plus Motion: green when an item verifies, red when it fails for good,
  // and a slide-in when a row first appears
  useEffect(() => {
    if (!gridApi) return
    for (const row of rows) {
      if (!row.flash || flashed.current.get(row.item_id) === row.flash_at) continue
      flashed.current.set(row.item_id, row.flash_at)
      // rows loaded from history a while ago shouldn't light up
      if (Date.now() - row.flash_at > 1500) continue
      flashGridRow(gridApi, wrapper.current, row.item_id, row.flash)
    }
  }, [gridApi, rows])

  const columnDefs = useMemo<ColDef<CatalogRow>[]>(
    () => [
      { headerName: "Item", field: "name", cellRenderer: ItemCell, flex: 2, minWidth: 190 },
      {
        headerName: "Price",
        field: "unit_price",
        width: 104,
        type: "rightAligned",
        cellClass: "font-mono tabular-nums",
        valueFormatter: (params) => (params.data ? money(params.value, params.data.currency) : ""),
        comparator: (a, b) => Number(a) - Number(b),
      },
      {
        headerName: "Page",
        field: "page_check",
        width: 82,
        headerTooltip: "The quote is on the page and its price matches the spec",
        cellClass: centered,
        headerClass: "ag-center-header",
        cellRenderer: (params: CustomCellRendererProps<CatalogRow>) =>
          params.data ? <CheckMark state={params.data.page_check} label="Page check" /> : null,
      },
      {
        headerName: "PayPal",
        field: "paypal_check",
        width: 88,
        headerTooltip: "A real sandbox order was created and read back with the same amount, currency and name",
        cellClass: centered,
        cellRenderer: (params: CustomCellRendererProps<CatalogRow>) =>
          params.data ? <CheckMark state={params.data.paypal_check} label="PayPal check" /> : null,
      },
      { headerName: "Repairs", field: "repairs", width: 104, cellRenderer: RepairsCell },
      {
        headerName: "PayPal order",
        field: "paypal_order_id",
        width: 190,
        cellRenderer: (params: CustomCellRendererProps<CatalogRow>) => (
          <CopyId value={params.data?.paypal_order_id || null} />
        ),
      },
      { headerName: "Status", field: "status", cellRenderer: StatusCell, flex: 3, minWidth: 220 },
    ],
    []
  )

  // keep the grid's selected row in step with the open drawer
  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    gridApi.forEachNode((node) => {
      node.setSelected(node.data?.item_id === selectedItemId)
    })
  }, [gridApi, selectedItemId, rows])

  return (
    <div ref={wrapper} className="h-full">
    <AgGridReact<CatalogRow>
      theme={calmTheme}
      columnDefs={columnDefs}
      defaultColDef={{ sortable: true, resizable: true, suppressMovable: true }}
      getRowId={(params: GetRowIdParams<CatalogRow>) => params.data.item_id}
      rowClassRules={rowClassRules}
      rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: false }}
      onRowClicked={(event: RowClickedEvent<CatalogRow>) => event.data && onPickItem(event.data.item_id)}
      onGridReady={onGridReady}
      animateRows
      tooltipShowDelay={400}
      suppressCellFocus
      overlayNoRowsTemplate='<span style="color: var(--muted-foreground); font-size: 13px">Items appear here one by one as they are checked.</span>'
    />
    </div>
  )
}
