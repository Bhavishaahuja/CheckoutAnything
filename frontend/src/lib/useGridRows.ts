// Feeds rows to AG Grid through transactions (add / update / remove) instead of replacing
// rowData, so only the rows that changed are touched and the grid can animate them.

import type { GridApi } from "ag-grid-community"
import { useCallback, useEffect, useRef, useState } from "react"

export function useGridRows<Row>(rows: Row[], getId: (row: Row) => string) {
  const [gridApi, setGridApi] = useState<GridApi<Row> | null>(null)
  const shown = useRef<Map<string, Row>>(new Map())
  const getIdRef = useRef(getId)
  useEffect(() => {
    getIdRef.current = getId
  }, [getId])

  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    const add: Row[] = []
    const update: Row[] = []
    const remove: Row[] = []
    const next = new Map<string, Row>()

    for (const row of rows) {
      const id = getIdRef.current(row)
      next.set(id, row)
      const before = shown.current.get(id)
      if (before === undefined) add.push(row)
      else if (before !== row) update.push(row)
    }
    for (const [id, row] of shown.current) {
      if (!next.has(id)) remove.push(row)
    }
    shown.current = next
    if (add.length || update.length || remove.length) {
      gridApi.applyTransaction({ add, update, remove })
    }
  }, [gridApi, rows])

  const onGridReady = useCallback((event: { api: GridApi<Row> }) => {
    shown.current = new Map()
    setGridApi(event.api)
  }, [])

  return { gridApi, onGridReady }
}
