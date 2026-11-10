// Feeds rows to AG Grid through transactions (add / update / remove) instead of replacing
// rowData, so only the rows that changed are touched, the grid can animate them, and it never
// reloads or loses its scroll position.
//
// With `patchInPlace`, a row that changed is written into the object the grid already holds
// and only its cells are refreshed. A transaction would clear AG Grid's undo stack, and the
// catalog needs Ctrl+Z to keep working after every save.

import type { GridApi, IRowNode } from "ag-grid-community"
import { useCallback, useEffect, useRef, useState } from "react"

interface Options<Row> {
  // true when two rows would draw the same, so nothing has to be sent to the grid
  same?: (a: Row, b: Row) => boolean
  patchInPlace?: boolean
  // keep the grid's rows in the order of `rows` (the catalog has an order of its own)
  keepOrder?: boolean
}

export function useGridRows<Row extends object>(rows: Row[], getId: (row: Row) => string, options: Options<Row> = {}) {
  const [gridApi, setGridApi] = useState<GridApi<Row> | null>(null)
  // the row objects the grid holds, by id
  const shown = useRef<Map<string, Row>>(new Map())
  // the row objects of the last render, by id, to spot rows that didn't change at all
  const sources = useRef<Map<string, Row>>(new Map())
  const getIdRef = useRef(getId)
  const optionsRef = useRef(options)
  useEffect(() => {
    getIdRef.current = getId
    optionsRef.current = options
  })

  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    const { same, patchInPlace, keepOrder } = optionsRef.current
    const add: Row[] = []
    const update: Row[] = []
    const remove: Row[] = []
    const patched: IRowNode<Row>[] = []
    const next = new Map<string, Row>()
    const nextSources = new Map<string, Row>()

    for (const row of rows) {
      const id = getIdRef.current(row)
      const before = shown.current.get(id)
      const unchanged = sources.current.get(id) === row
      nextSources.set(id, row)
      if (before === undefined) {
        // the grid gets its own copy: editing a cell writes into the row object, and React's
        // state should never change under its feet
        const own = { ...row }
        next.set(id, own)
        add.push(own)
        continue
      }
      if (unchanged || same?.(before, row)) {
        next.set(id, before)
        continue
      }
      if (patchInPlace) {
        const node = gridApi.getRowNode(id)
        if (node) {
          Object.assign(before, row)
          next.set(id, before)
          patched.push(node)
          continue
        }
      }
      const own = { ...row }
      next.set(id, own)
      update.push(own)
    }
    for (const [id, row] of shown.current) {
      if (!next.has(id)) remove.push(row)
    }
    shown.current = next
    sources.current = nextSources

    if (add.length || update.length || remove.length) {
      gridApi.applyTransaction({ add, update, remove })
    }
    if (patched.length) {
      gridApi.refreshCells({ rowNodes: patched, force: true })
    }
    if (keepOrder) {
      const have: string[] = []
      gridApi.forEachNode((node) => {
        if (node.id) have.push(node.id)
      })
      const wanted = rows.map((row) => getIdRef.current(row))
      if (wanted.length === have.length && wanted.some((id, index) => id !== have[index])) {
        // the same row objects in a new order. with getRowId the grid keeps its row nodes
        gridApi.setGridOption("rowData", wanted.map((id) => next.get(id) as Row))
      }
    }
  }, [gridApi, rows])

  const onGridReady = useCallback((event: { api: GridApi<Row> }) => {
    ;(window as unknown as { __grids: unknown[] }).__grids = [...((window as unknown as { __grids?: unknown[] }).__grids || []), event.api] // DEBUG
    shown.current = new Map()
    sources.current = new Map()
    setGridApi(event.api)
  }, [])

  return { gridApi, onGridReady }
}
