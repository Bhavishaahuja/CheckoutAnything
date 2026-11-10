// The catalog on the Connect screen: what the agent imported, and the merchant's review of it.
//
// While a store is connecting, rows arrive one by one, flip to verified or failed in place and
// flash when they do. Once it is done the grid becomes the review surface: cells the agent was
// unsure about are amber with the reason on hover, cells can be edited (and undone), rows can
// be reordered, and clean rows can be published to PayPal in bulk.

import type {
  CellClassParams,
  CellKeyDownEvent,
  CellValueChangedEvent,
  ColDef,
  DataTypeDefinition,
  GetRowIdParams,
  GridApi,
  RowClassRules,
  RowDragEndEvent,
  RowDragEvent,
  RowDragMoveEvent,
  SuppressKeyboardEventParams,
} from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import { Check, Download, PanelRightOpen, Redo2, RotateCcw, Store as StoreIcon, TriangleAlert, Undo2, Upload } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { CheckMark, CopyId, RowStatusPill } from "@/components/bits"
import { ColumnsMenu } from "@/components/grid/ColumnsMenu"
import { EditableHeader, type HeaderContext } from "@/components/grid/EditableHeader"
import { FLAG_COLUMN, FlagTooltip, flagForColumn } from "@/components/grid/FlagTooltip"
import { createOverlayStore, GridOverlay, type OverlayContent, type OverlayStore } from "@/components/grid/GridOverlay"
import { PriceEditor } from "@/components/grid/PriceEditor"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { dayStamp, money, shortDateTime, slugify } from "@/lib/format"
import { flashGridRow } from "@/lib/gridFlash"
import { useGridLayout } from "@/lib/gridState"
import { calmTheme } from "@/lib/gridTheme"
import type { CatalogRow, FlagField, ItemPatch, ReviewResponse, StoreStatus } from "@/lib/types"
import { useGridRows } from "@/lib/useGridRows"
import { cn } from "@/lib/utils"

const NO_CATEGORY = "Uncategorized"
const PAGE_SIZES = [5, 10, 25, 50]

interface CatalogContext extends HeaderContext {
  overlay: OverlayStore
  confirmFlag: (itemId: string, field: FlagField) => void
  openItem: (itemId: string) => void
  openItemId: string | null
  editable: boolean
}

type CellProps = CustomCellRendererProps<CatalogRow, unknown, CatalogContext>

const FIELD_WORDS: Record<FlagField, string> = { name: "name", unit_price: "price", available: "availability" }

function openFlagCount(row: CatalogRow) {
  let count = 0
  for (const flag of Object.values(row.flags)) {
    if (flag && !flag.resolved) count += 1
  }
  return count
}

// the small check on an amber cell: "I looked, this is right"
function ConfirmButton({ row, colId, context }: { row: CatalogRow; colId: string; context: CatalogContext }) {
  const flag = flagForColumn(row, colId)
  if (!flag || flag.resolved || !context.editable) return null
  return (
    <button
      type="button"
      tabIndex={-1}
      aria-label={"Confirm the " + FIELD_WORDS[flag.field] + " of " + row.name + " is right"}
      title="Looks right (Shift+Enter)"
      onClick={(event) => {
        event.stopPropagation()
        context.confirmFlag(row.item_id, flag.field)
      }}
      onDoubleClick={(event) => event.stopPropagation()}
      className="ml-auto flex size-6 shrink-0 items-center justify-center rounded-md border border-warn/40 bg-card text-warn hover:bg-warn hover:text-card"
    >
      <Check className="size-3.5" strokeWidth={3} />
    </button>
  )
}

function FlagMark({ row, colId }: { row: CatalogRow; colId: string }) {
  const flag = flagForColumn(row, colId)
  if (!flag || flag.resolved) return null
  // amber is never the only signal: the icon and its label say the same thing
  return (
    <span className="shrink-0 text-warn" role="img" aria-label="Needs a look">
      <TriangleAlert className="size-3.5" />
    </span>
  )
}

function ItemCell({ data, context }: CellProps) {
  if (!data) return null
  const parts = []
  if (data.variant_count > 0) parts.push(data.variant_count + (data.variant_count === 1 ? " variant" : " variants"))
  if (data.add_on_count > 0) parts.push(data.add_on_count + (data.add_on_count === 1 ? " add-on" : " add-ons"))
  return (
    <div className="flex h-full min-w-0 items-center gap-2">
      <FlagMark row={data} colId="name" />
      <div className="flex min-w-0 flex-col justify-center leading-tight">
        <span className="truncate font-medium">{data.name}</span>
        {parts.length > 0 && <span className="truncate text-[11px] text-muted-foreground">{parts.join(", ")}</span>}
      </div>
      <ConfirmButton row={data} colId="name" context={context} />
    </div>
  )
}

function PriceCell({ data, valueFormatted, context }: CellProps) {
  if (!data) return null
  return (
    <div className="flex h-full min-w-0 items-center justify-end gap-2">
      <FlagMark row={data} colId="unit_price" />
      <span className="truncate font-mono tabular-nums">{valueFormatted}</span>
      <ConfirmButton row={data} colId="unit_price" context={context} />
    </div>
  )
}

function RepairsCell({ data }: CellProps) {
  if (!data) return null
  if (data.repairs === 0) return <span className="text-muted-foreground/60">None</span>
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

function StatusCell({ data, context }: CellProps) {
  if (!data) return null
  const showReason = data.reason && data.status !== "verified"
  return (
    <div className="flex h-full min-w-0 items-center gap-2">
      <FlagMark row={data} colId="status" />
      <RowStatusPill status={data.status} />
      {showReason && <span className="truncate text-xs text-muted-foreground">{data.reason}</span>}
      <ConfirmButton row={data} colId="status" context={context} />
    </div>
  )
}

function OpenCell({ data, context }: CellProps) {
  if (!data) return null
  return (
    <button
      type="button"
      tabIndex={-1}
      aria-label={"Open the spec for " + data.name}
      title="Source quote, checks and spec"
      onClick={() => context.openItem(data.item_id)}
      className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <PanelRightOpen className="size-4" />
    </button>
  )
}

// cell data types, so nothing shows raw: money for "29.00" strings, timestamps for ISO dates
const dataTypeDefinitions: Record<string, DataTypeDefinition<CatalogRow>> = {
  money: {
    baseDataType: "text",
    extendsDataType: "text",
    // the price column adds the store's currency, this is the fallback for the type
    valueFormatter: (params) => (params.value === null || params.value === undefined || params.value === "" ? "" : money(params.value)),
  },
  timestamp: {
    baseDataType: "dateTimeString",
    extendsDataType: "dateTimeString",
    dateParser: (value) => (value ? new Date(value) : undefined),
    dateFormatter: (value) => (value ? value.toISOString() : undefined),
    valueFormatter: (params) => (params.value ? shortDateTime(params.value) : "Not checked yet"),
  },
}

const rowClassRules: RowClassRules<CatalogRow> = {
  "row-dim": (params) => params.data?.status === "unavailable",
  "row-open": (params) => Boolean(params.data) && params.data?.item_id === (params.context as CatalogContext).openItemId,
}

const flagClassRules = {
  "cell-flag": (params: CellClassParams<CatalogRow>) => {
    const flag = flagForColumn(params.data, params.column.getColId())
    return Boolean(flag) && !flag!.resolved
  },
}

function flagTooltip(row: CatalogRow | undefined, colId: string) {
  const flag = flagForColumn(row, colId)
  return flag && !flag.resolved ? flag.reasons.join(" ") : undefined
}

// what two rows have to share to draw the same. flash fields don't count
function sameRow(a: CatalogRow, b: CatalogRow) {
  for (const key of Object.keys(b) as (keyof CatalogRow)[]) {
    if (key === "flash" || key === "flash_at") continue
    if (key === "flags") {
      if (JSON.stringify(a.flags) !== JSON.stringify(b.flags)) return false
    } else if (a[key] !== b[key]) return false
  }
  return true
}

// the grid starts empty (never undefined rowData), rows then arrive as transactions
const NO_ROWS: CatalogRow[] = []
const centered = "flex items-center justify-center"

type SaveState = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; text: string } | { kind: "error"; text: string }

export function CatalogGrid({
  storeId,
  rows,
  review,
  merchantName,
  status,
  loadingStep,
  storeError,
  selectedItemId,
  onPickItem,
  reload,
  onConnectDemo,
}: {
  storeId: number | null
  rows: CatalogRow[]
  review: ReviewResponse | null
  merchantName: string
  status: StoreStatus | "idle"
  // what the loading overlay says while there are no rows yet
  loadingStep: { label: string; progress: number }
  storeError: string | null
  selectedItemId: string | null
  onPickItem: (itemId: string) => void
  reload: () => Promise<void>
  onConnectDemo?: () => void
}) {
  const layout = useGridLayout("catalog")
  const wrapper = useRef<HTMLDivElement>(null)
  const editable = Boolean(review?.editable) && status !== "connecting" && storeId !== null
  const [save, setSave] = useState<SaveState>({ kind: "idle" })
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [undoSize, setUndoSize] = useState(0)
  const [redoSize, setRedoSize] = useState(0)
  const [publishing, setPublishing] = useState(false)

  // What the grid is given. While saves are in flight the rows are held still: an answer that
  // is already out of date must not overwrite what was typed since (a fast run of Ctrl+Z would
  // otherwise skip steps). After a drop the rows show in the new order right away.
  const [pending, setPending] = useState(0)
  const [droppedOrder, setDroppedOrder] = useState<string[] | null>(null)
  const held = useRef(rows)
  const ordered = useMemo(() => {
    if (!droppedOrder) return rows
    const place = new Map(droppedOrder.map((id, index) => [id, index]))
    return [...rows].sort((a, b) => (place.get(a.item_id) ?? 0) - (place.get(b.item_id) ?? 0))
  }, [rows, droppedOrder])
  if (pending === 0 || droppedOrder) held.current = ordered

  const { gridApi, onGridReady } = useGridRows(held.current, (row) => row.item_id, {
    same: sameRow,
    // once the run is over, updates are written in place so AG Grid's undo stack survives a save
    patchInPlace: editable,
    keepOrder: true,
  })

  // ---- saving: one change at a time, in the order they were made ----

  const queue = useRef<Promise<void>>(Promise.resolve())
  const reloadRef = useRef(reload)
  useEffect(() => {
    reloadRef.current = reload
  })

  const waiting = useRef(0)
  const enqueue = useCallback((work: () => Promise<unknown>, done: string) => {
    setSave({ kind: "saving" })
    waiting.current += 1
    setPending(waiting.current)
    queue.current = queue.current.then(async () => {
      let failed: string | null = null
      try {
        await work()
      } catch (problem) {
        failed = problem instanceof Error ? problem.message : "The change wasn't saved"
      }
      // once nothing else is waiting, the grid goes back to what the API has: a saved change
      // shows its side effects (the flag clears, the PayPal order id changes), a refused one
      // is reverted
      if (waiting.current === 1) await reloadRef.current().catch(() => {})
      waiting.current -= 1
      setPending(waiting.current)
      if (waiting.current === 0) setDroppedOrder(null)
      setSave((was) => {
        if (failed) return { kind: "error", text: failed }
        // an error from earlier in the same burst stays up
        return was.kind === "error" && waiting.current > 0 ? was : { kind: "saved", text: done }
      })
    })
    return queue.current
  }, [])

  const patch = useCallback(
    (itemId: string, body: ItemPatch, done: string) => {
      if (storeId === null) return Promise.resolve()
      return enqueue(() => api.patchItem(storeId, itemId, body), done)
    },
    [enqueue, storeId]
  )

  // ---- the grid's context: one object, kept up to date ----

  const overlay = useMemo(
    () =>
      createOverlayStore({
        loading: { title: "Agent is reading the store..." },
        empty: { title: "No store connected yet" },
        noMatch: { title: "No item matches the filters", actionLabel: "Clear filters", onAction: () => {} },
      }),
    []
  )
  const context = useMemo<CatalogContext>(
    () => ({ overlay, confirmFlag: () => {}, openItem: () => {}, openItemId: null, editable: false }),
    [overlay]
  )
  // keyed on the labels themselves, not on `review`: the review is reloaded after every save,
  // and new column definitions would make the grid drop its undo history
  const columnsKey = JSON.stringify(review?.columns || [])
  const columnInfo = useMemo(
    () => new Map((JSON.parse(columnsKey) as ReviewResponse["columns"]).map((column) => [column.field, column])),
    [columnsKey]
  )
  context.editable = editable
  context.openItem = onPickItem
  context.confirmFlag = (itemId, field) => void patch(itemId, { resolve: [field] }, "Confirmed")
  context.paypalField = (colId) => columnInfo.get(colId)?.paypal_field || null
  context.renameColumn = editable
    ? (colId, label) => {
        if (storeId === null) return Promise.resolve()
        return enqueue(() => api.renameColumn(storeId, colId, label), "Column renamed")
      }
    : undefined

  // ---- overlays ----

  const failedEmpty = status === "failed" && rows.length === 0
  useEffect(() => {
    const content: OverlayContent = {
      loading: { title: "Agent is reading the store...", step: loadingStep.label, progress: loadingStep.progress },
      empty: failedEmpty
        ? { icon: <TriangleAlert />, title: "This store has no catalog", hint: storeError || "The run ended before any item was read." }
        : {
            icon: <StoreIcon />,
            title: "No store connected yet",
            hint: "Paste a store URL above and its items show up here one by one as they are checked.",
            actionLabel: onConnectDemo ? "Connect a demo store" : undefined,
            onAction: onConnectDemo,
          },
      noMatch: {
        title: "No item matches the filters",
        actionLabel: "Clear filters",
        onAction: () => gridApi?.setFilterModel(null),
      },
    }
    overlay.set(content)
  }, [overlay, loadingStep.label, loadingStep.progress, failedEmpty, storeError, onConnectDemo, gridApi])

  // ---- flashes while the run is live ----

  const flashed = useRef<Map<string, number>>(new Map())
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

  // the row whose spec drawer is open
  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    context.openItemId = selectedItemId
    gridApi.redrawRows()
  }, [gridApi, context, selectedItemId])

  // ---- columns ----

  const categoriesKey = (review?.categories || []).join("|")
  const columnDefs = useMemo<ColDef<CatalogRow>[]>(() => {
    const label = (field: string, fallback: string) => columnInfo.get(field)?.label || fallback
    const categoryValues = [NO_CATEGORY, ...(categoriesKey ? categoriesKey.split("|") : [])]
    return [
      {
        headerName: label("name", "Item"),
        field: "name",
        cellDataType: "text",
        pinned: "left",
        lockPinned: true,
        lockVisible: true,
        rowDrag: true,
        editable,
        cellEditor: "agTextCellEditor",
        cellEditorParams: {
          maxLength: 127,
          getValidationErrors: (params: { value: unknown }) =>
            String(params.value ?? "").trim() === "" ? ["An item needs a name"] : null,
        },
        cellRenderer: ItemCell,
        cellClassRules: flagClassRules,
        tooltipValueGetter: (params) => flagTooltip(params.data, "name"),
        filter: true,
        width: 240,
        minWidth: 190,
      },
      {
        headerName: label("unit_price", "Price"),
        field: "unit_price",
        cellDataType: "money",
        type: "rightAligned",
        editable,
        valueFormatter: (params) => (params.data ? money(params.data.unit_price, params.data.currency) : ""),
        cellEditor: PriceEditor,
        cellEditorPopup: true,
        cellEditorPopupPosition: "over",
        cellRenderer: PriceCell,
        cellClassRules: flagClassRules,
        tooltipValueGetter: (params) => flagTooltip(params.data, "unit_price"),
        comparator: (a, b) => Number(a) - Number(b),
        filter: "agNumberColumnFilter",
        filterValueGetter: (params) => Number(params.data?.unit_price),
        width: 132,
      },
      {
        headerName: label("published", "Live on PayPal"),
        field: "published",
        cellDataType: "boolean",
        // only something verified can go live, and the checkbox says no while a field is amber
        editable: (params) => editable && params.data?.status === "verified",
        valueSetter: (params) => {
          if (params.newValue && params.data.blocked_reason) {
            setSave({ kind: "error", text: params.data.blocked_reason + ". Confirm or fix the amber cells first." })
            return false
          }
          params.data.published = Boolean(params.newValue)
          return true
        },
        cellClass: centered,
        width: 136,
      },
      {
        headerName: label("status", "Status"),
        field: "status",
        colId: "status",
        cellRenderer: StatusCell,
        cellClassRules: flagClassRules,
        tooltipValueGetter: (params) =>
          flagTooltip(params.data, "status") || (params.data?.status !== "verified" ? params.data?.reason || undefined : undefined),
        filter: true,
        width: 230,
        minWidth: 170,
      },
      {
        headerName: label("category", "Category"),
        field: "category",
        cellDataType: "text",
        editable,
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: categoryValues },
        valueGetter: (params) => params.data?.category || NO_CATEGORY,
        valueSetter: (params) => {
          params.data.category = params.newValue === NO_CATEGORY ? null : params.newValue
          return true
        },
        cellClass: (params) => (params.data?.category ? "" : "text-muted-foreground"),
        filter: true,
        width: 150,
      },
      {
        headerName: label("stock", "Stock"),
        field: "stock",
        cellDataType: "number",
        type: "rightAligned",
        editable,
        cellEditor: "agNumberCellEditor",
        cellEditorParams: { min: 0, max: 1_000_000, precision: 0, step: 1 },
        valueFormatter: (params) =>
          params.value === null || params.value === undefined ? "Not tracked" : new Intl.NumberFormat("en-US").format(params.value),
        cellClass: (params) => cn("tabular-nums", (params.value === null || params.value === undefined) && "text-muted-foreground"),
        filter: true,
        width: 116,
      },
      {
        headerName: label("description", "Description"),
        field: "description",
        cellDataType: "text",
        editable,
        cellEditor: "agLargeTextCellEditor",
        cellEditorPopup: true,
        cellEditorParams: { maxLength: 300, rows: 6, cols: 46 },
        valueFormatter: (params) => params.value || "No description",
        cellClass: (params) => (params.value ? "" : "text-muted-foreground"),
        tooltipValueGetter: (params) => params.value || undefined,
        filter: true,
        width: 220,
      },
      {
        headerName: "Page",
        field: "page_check",
        colId: "page_check",
        context: { renameable: false },
        width: 82,
        headerTooltip: "The quote is on the page and its price matches the spec",
        cellClass: centered,
        sortable: false,
        cellRenderer: (params: CellProps) => (params.data ? <CheckMark state={params.data.page_check} label="Page check" /> : null),
      },
      {
        headerName: "PayPal",
        field: "paypal_check",
        colId: "paypal_check",
        context: { renameable: false },
        width: 88,
        headerTooltip: "A real sandbox order was created and read back with the same amount, currency and name",
        cellClass: centered,
        sortable: false,
        cellRenderer: (params: CellProps) => (params.data ? <CheckMark state={params.data.paypal_check} label="PayPal check" /> : null),
      },
      {
        headerName: "Repairs",
        field: "repairs",
        context: { renameable: false },
        width: 104,
        cellRenderer: RepairsCell,
      },
      {
        headerName: label("paypal_order_id", "PayPal order"),
        field: "paypal_order_id",
        width: 190,
        cellRenderer: (params: CellProps) => <CopyId value={params.data?.paypal_order_id || null} />,
      },
      {
        headerName: label("checked_at", "Checked"),
        field: "checked_at",
        cellDataType: "timestamp",
        cellClass: "text-muted-foreground tabular-nums",
        width: 150,
      },
      {
        headerName: "",
        colId: "open",
        pinned: "right",
        lockPinned: true,
        lockVisible: true,
        context: { renameable: false },
        width: 52,
        maxWidth: 52,
        sortable: false,
        resizable: false,
        suppressMovable: true,
        cellClass: centered,
        cellRenderer: OpenCell,
      },
    ]
  }, [columnInfo, categoriesKey, editable])

  const defaultColDef = useMemo<ColDef<CatalogRow>>(
    () => ({
      sortable: true,
      resizable: true,
      headerComponent: EditableHeader,
      tooltipComponent: FlagTooltip,
      // Shift+Enter on an amber cell confirms it instead of opening the editor
      suppressKeyboardEvent: (params: SuppressKeyboardEventParams<CatalogRow>) => {
        if (params.editing || params.event.key !== "Enter" || !params.event.shiftKey) return false
        const flag = flagForColumn(params.data, params.column.getColId())
        return Boolean(flag) && !flag!.resolved
      },
    }),
    []
  )

  // ---- edits ----

  const refreshUndo = useCallback((api: GridApi<CatalogRow>) => {
    setUndoSize(api.getCurrentUndoSize())
    setRedoSize(api.getCurrentRedoSize())
  }, [])

  const onCellValueChanged = useCallback(
    (event: CellValueChangedEvent<CatalogRow>) => {
      refreshUndo(event.api)
      const row = event.data
      const field = event.column.getColId()
      const body: ItemPatch = {}
      if (field === "name") body.name = String(event.newValue ?? "")
      else if (field === "description") body.description = String(event.newValue ?? "")
      else if (field === "unit_price") body.unit_price = String(event.newValue ?? "")
      else if (field === "category") body.category = row.category
      else if (field === "stock") body.stock = row.stock ?? null
      else if (field === "published") body.published = row.published
      else return
      // an undo or redo is saved the same way as the edit it reverses, so undo also un-saves
      const verb = event.source === "undo" ? "Undone and saved" : event.source === "redo" ? "Redone and saved" : "Saved"
      void patch(row.item_id, body, verb)
    },
    [patch, refreshUndo]
  )

  const onCellKeyDown = useCallback(
    (event: CellKeyDownEvent<CatalogRow>) => {
      const key = event.event as KeyboardEvent | undefined
      if (!key || key.key !== "Enter" || !key.shiftKey || !event.data || !editable) return
      const flag = flagForColumn(event.data, event.column.getColId())
      if (flag && !flag.resolved) context.confirmFlag(event.data.item_id, flag.field)
    },
    [context, editable]
  )

  // ---- row order ----

  // Managed row dragging is switched off by AG Grid when pagination is on, so the move is done
  // here: a line shows where the row will land, and the drop saves the new order.
  const dropPlace = (event: RowDragEvent<CatalogRow>): "above" | "below" | null => {
    const over = event.overNode
    if (!over || !over.data || over === event.node || over.rowTop === null || !over.rowHeight) return null
    return event.y < over.rowTop + over.rowHeight / 2 ? "above" : "below"
  }

  const onRowDragMove = useCallback((event: RowDragMoveEvent<CatalogRow>) => {
    const place = dropPlace(event)
    event.api.setRowDropPositionIndicator(place && event.overNode ? { row: event.overNode, dropIndicatorPosition: place } : null)
  }, [])

  const onRowDragEnd = useCallback(
    (event: RowDragEndEvent<CatalogRow>) => {
      event.api.setRowDropPositionIndicator(null)
      const place = dropPlace(event)
      const moving = event.node.data
      const over = event.overNode?.data
      if (!place || !moving || !over || storeId === null) return
      const order = held.current.map((row) => row.item_id).filter((id) => id !== moving.item_id)
      const index = order.indexOf(over.item_id) + (place === "below" ? 1 : 0)
      order.splice(index, 0, moving.item_id)
      setDroppedOrder(order)
      void enqueue(() => api.reorderItems(storeId, order), "Order saved")
    },
    [enqueue, storeId]
  )

  // dragging only makes sense while the rows are in the merchant's own order
  const [rearranged, setRearranged] = useState(false)
  const checkRearranged = useCallback((grid: GridApi<CatalogRow>) => {
    setRearranged(grid.isAnyFilterPresent() || grid.getColumnState().some((column) => Boolean(column.sort)))
  }, [])

  // ---- the toolbar ----

  const byId = useMemo(() => new Map(rows.map((row) => [row.item_id, row])), [rows])
  const selected = selectedIds.map((id) => byId.get(id)).filter((row): row is CatalogRow => Boolean(row))
  const toPublish = selected.filter((row) => !row.published)
  const stillAmber = toPublish.filter((row) => openFlagCount(row) > 0)
  const needsLook = rows.reduce((total, row) => total + openFlagCount(row), 0)
  const flaggedTotal = rows.reduce((total, row) => total + Object.keys(row.flags).length, 0)
  const takeOffline = selected.length > 0 && toPublish.length === 0

  let publishHint: string | null = null
  if (editable && selected.length === 0) publishHint = "Tick rows to publish them."
  if (stillAmber.length > 0) {
    publishHint =
      stillAmber.length +
      (stillAmber.length === 1 ? " selected item still has" : " selected items still have") +
      " amber cells. Confirm or fix them first."
  }

  const publish = async () => {
    if (storeId === null || !gridApi) return
    const ids = (takeOffline ? selected : toPublish).map((row) => row.item_id)
    setPublishing(true)
    await enqueue(
      () => api.publishItems(storeId, ids, !takeOffline),
      takeOffline ? ids.length + " taken offline" : ids.length + " published to PayPal"
    )
    setPublishing(false)
    if (gridApi.isDestroyed()) return
    gridApi.deselectAll()
    if (!takeOffline) {
      for (const id of ids) flashGridRow(gridApi, wrapper.current, id, "ok")
    }
  }

  const jumpToNextFlag = () => {
    if (!gridApi) return
    let target: { rowIndex: number; colId: string } | null = null
    gridApi.forEachNodeAfterFilterAndSort((node) => {
      if (target || !node.data || node.rowIndex === null) return
      for (const field of Object.keys(node.data.flags) as FlagField[]) {
        if (!node.data.flags[field]?.resolved) {
          target = { rowIndex: node.rowIndex, colId: FLAG_COLUMN[field] }
          return
        }
      }
    })
    if (!target) return
    const found = target as { rowIndex: number; colId: string }
    // the row may be on another page
    gridApi.paginationGoToPage(Math.floor(found.rowIndex / gridApi.paginationGetPageSize()))
    gridApi.ensureIndexVisible(found.rowIndex, "middle")
    gridApi.ensureColumnVisible(found.colId)
    gridApi.setFocusedCell(found.rowIndex, found.colId)
  }

  const exportCsv = () => {
    if (!gridApi) return
    gridApi.exportDataAsCsv({
      fileName: slugify(merchantName || "store") + "-catalog-" + dayStamp(new Date()) + ".csv",
      columnKeys: ["name", "category", "description", "unit_price", "stock", "published", "status", "paypal_order_id", "checked_at"],
      exportedRows: "all",
      // the cleaned values a person reads in the grid, not the raw ones
      processCellCallback: (params) => {
        const colId = params.column.getColId()
        const row = params.node?.data as CatalogRow | undefined
        if (!row) return ""
        if (colId === "published") return row.published ? "Yes" : "No"
        if (colId === "status") return STATUS_WORDS[row.status]
        if (colId === "unit_price") return money(row.unit_price, row.currency)
        if (colId === "stock") return row.stock === null ? "Not tracked" : String(row.stock)
        if (colId === "category") return row.category || NO_CATEGORY
        if (colId === "checked_at") return row.checked_at ? shortDateTime(row.checked_at) : ""
        return params.value ?? ""
      },
    })
  }

  const columnNote = useCallback((colId: string) => columnInfo.get(colId)?.paypal_field || null, [columnInfo])
  const hasRows = rows.length > 0

  return (
    <div className="flex h-full flex-col">
      {hasRows && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2">
          {/* the counter: how many cells the agent wasn't sure about are still open */}
          {flaggedTotal > 0 && needsLook > 0 && (
            <button
              type="button"
              onClick={jumpToNextFlag}
              title="Go to the next one"
              className="flex h-8 items-center gap-1.5 rounded-lg bg-warn-soft px-2.5 text-[13px] font-medium text-warn hover:brightness-95"
            >
              <TriangleAlert className="size-3.5" aria-hidden />
              <span aria-live="polite">
                {needsLook} {needsLook === 1 ? "field needs" : "fields need"} a look
              </span>
            </button>
          )}
          {flaggedTotal > 0 && needsLook === 0 && (
            <span className="flex h-8 items-center gap-1.5 rounded-lg bg-ok-soft px-2.5 text-[13px] font-medium text-ok" aria-live="polite">
              <Check className="size-3.5" strokeWidth={3} aria-hidden /> 0 fields need a look
            </span>
          )}

          {editable && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant={takeOffline ? "outline" : "default"}
                disabled={publishing || selected.length === 0 || stillAmber.length > 0}
                aria-describedby={publishHint ? "publish-hint" : undefined}
                onClick={() => void publish()}
              >
                <Upload />
                {takeOffline
                  ? "Take " + selected.length + " offline"
                  : toPublish.length > 0
                    ? "Publish " + toPublish.length + " to PayPal"
                    : "Publish to PayPal"}
              </Button>
              {publishHint && (
                <span id="publish-hint" className={cn("text-xs", stillAmber.length > 0 ? "font-medium text-warn" : "text-muted-foreground")}>
                  {publishHint}
                </span>
              )}
            </div>
          )}

          <div className="ml-auto flex items-center gap-1.5">
            <span
              role="status"
              className={cn(
                "max-w-72 truncate text-xs",
                save.kind === "error" ? "font-medium text-bad" : "text-muted-foreground"
              )}
              title={save.kind === "error" ? save.text : undefined}
            >
              {save.kind === "saving" && "Saving..."}
              {save.kind === "saved" && save.text}
              {save.kind === "error" && save.text}
            </span>
            {editable && (
              <>
                <Button size="sm" variant="ghost" className="px-2" disabled={undoSize === 0} onClick={() => gridApi?.undoCellEditing()} aria-label="Undo the last edit" title="Undo (Ctrl+Z)">
                  <Undo2 />
                </Button>
                <Button size="sm" variant="ghost" className="px-2" disabled={redoSize === 0} onClick={() => gridApi?.redoCellEditing()} aria-label="Redo the edit" title="Redo (Ctrl+Y)">
                  <Redo2 />
                </Button>
              </>
            )}
            <Button size="sm" variant="outline" onClick={exportCsv} title="Download the catalog as CSV">
              <Download /> <span className="hidden sm:inline">Export CSV</span>
            </Button>
            <ColumnsMenu gridApi={gridApi} note={columnNote} />
            <Button size="sm" variant="ghost" onClick={layout.resetLayout} disabled={!layout.hasSaved} title="Put the columns, sort and filters back to the defaults">
              <RotateCcw /> <span className="hidden sm:inline">Reset layout</span>
            </Button>
          </div>
        </div>
      )}

      <div ref={wrapper} className="min-h-0 flex-1">
        <AgGridReact<CatalogRow>
          key={layout.layoutVersion}
          theme={calmTheme}
          rowData={NO_ROWS}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          dataTypeDefinitions={dataTypeDefinitions}
          context={context}
          getRowId={(params: GetRowIdParams<CatalogRow>) => params.data.item_id}
          rowClassRules={rowClassRules}
          // state
          initialState={layout.initialState}
          onStateUpdated={layout.onStateUpdated}
          // selection and bulk publish
          rowSelection={{
            mode: "multiRow",
            checkboxes: editable,
            headerCheckbox: editable,
            enableClickSelection: false,
            isRowSelectable: (node) => node.data?.status === "verified",
            hideDisabledCheckboxes: true,
          }}
          selectionColumnDef={{ pinned: "left", lockPinned: true, width: 44, maxWidth: 44, suppressMovable: true }}
          onSelectionChanged={(event) => setSelectedIds(event.api.getSelectedRows().map((row) => row.item_id))}
          // editing
          undoRedoCellEditing
          undoRedoCellEditingLimit={50}
          stopEditingWhenCellsLoseFocus
          invalidEditValueMode="block"
          onCellValueChanged={onCellValueChanged}
          onCellKeyDown={onCellKeyDown}
          onUndoEnded={(event) => refreshUndo(event.api)}
          onRedoEnded={(event) => refreshUndo(event.api)}
          onModelUpdated={(event) => refreshUndo(event.api)}
          // row order
          suppressRowDrag={!editable || rearranged}
          onRowDragMove={onRowDragMove}
          onRowDragEnd={onRowDragEnd}
          onRowDragLeave={(event) => event.api.setRowDropPositionIndicator(null)}
          onRowDragCancel={(event) => event.api.setRowDropPositionIndicator(null)}
          onSortChanged={(event) => checkRearranged(event.api)}
          onFilterChanged={(event) => checkRearranged(event.api)}
          // pagination
          pagination
          paginationPageSize={10}
          paginationPageSizeSelector={PAGE_SIZES}
          // overlays
          loading={status === "connecting" && rows.length === 0}
          overlayComponent={GridOverlay}
          // the rest
          onGridReady={onGridReady}
          animateRows
          tooltipShowDelay={300}
          tooltipHideDelay={12000}
          tooltipInteraction
        />
      </div>
    </div>
  )
}

const STATUS_WORDS: Record<CatalogRow["status"], string> = {
  checking: "Checking",
  repairing: "Repairing",
  verified: "Verified",
  failed: "Failed",
  unavailable: "Not for sale",
}
