// Find for a grid: every match inside the cells is highlighted, a counter says "2 of 5", and
// next / previous walk through them, scrolling the grid to each one.
//
// AG Grid has a Find feature, but it is an Enterprise module. This one is built on Community
// APIs: the text of each cell comes from getCellValue (formatted, so it is what the cell
// shows), cells draw their own highlights with <FindText>, and ensureNodeVisible /
// ensureColumnVisible bring the active match into view.

import type { GridApi, IRowNode } from "ag-grid-community"
import type { CustomCellRendererProps } from "ag-grid-react"
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"

interface Match {
  rowId: string
  colId: string
  // which occurrence inside the cell, 0 first
  index: number
  node: IRowNode
}

interface FindSnapshot {
  term: string
  active: { rowId: string; colId: string; index: number } | null
}

export interface FindStore {
  get: () => FindSnapshot
  subscribe: (listener: () => void) => () => void
}

const EMPTY: FindSnapshot = { term: "", active: null }

function occurrences(text: string, term: string): number {
  if (!term) return 0
  const haystack = text.toLowerCase()
  let count = 0
  let from = haystack.indexOf(term)
  while (from !== -1) {
    count += 1
    from = haystack.indexOf(term, from + term.length)
  }
  return count
}

// Draws text with the current find matches marked. Used by every findable cell.
export function FindText({ text, rowId, colId, store }: { text: string; rowId: string; colId: string; store: FindStore }) {
  const snapshot = useSyncExternalStore(store.subscribe, store.get)
  const term = snapshot.term
  if (!term || !text) return <>{text}</>

  const lowered = text.toLowerCase()
  const parts = []
  let cursor = 0
  let index = 0
  let from = lowered.indexOf(term)
  while (from !== -1) {
    if (from > cursor) parts.push(text.slice(cursor, from))
    const active =
      snapshot.active !== null && snapshot.active.rowId === rowId && snapshot.active.colId === colId && snapshot.active.index === index
    parts.push(
      <mark key={index} className={active ? "find-hit find-hit-active" : "find-hit"}>
        {text.slice(from, from + term.length)}
      </mark>
    )
    cursor = from + term.length
    index += 1
    from = lowered.indexOf(term, cursor)
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

// The default renderer for a findable column: the formatted value, with matches marked.
export function FindCell(props: CustomCellRendererProps<unknown, unknown, { find: FindStore }>) {
  const text = props.valueFormatted ?? (props.value === null || props.value === undefined ? "" : String(props.value))
  return (
    <span className="block truncate">
      <FindText text={text} rowId={props.node.id || ""} colId={props.column?.getColId() || ""} store={props.context.find} />
    </span>
  )
}

export function useGridFind<Row>(gridApi: GridApi<Row> | null) {
  const [term, setTermState] = useState("")
  const [matches, setMatches] = useState<Match[]>([])
  const [position, setPosition] = useState(0)

  const snapshot = useRef<FindSnapshot>(EMPTY)
  const listeners = useRef(new Set<() => void>())
  const store = useMemo<FindStore>(
    () => ({
      get: () => snapshot.current,
      subscribe: (listener) => {
        listeners.current.add(listener)
        return () => listeners.current.delete(listener)
      },
    }),
    []
  )
  const publish = useCallback((next: FindSnapshot) => {
    snapshot.current = next
    for (const listener of listeners.current) listener()
  }, [])

  const needle = term.trim().toLowerCase()

  // every match, in reading order: pinned rows first, then the rows as sorted and filtered,
  // and left to right inside a row
  const collect = useCallback(() => {
    if (!gridApi || gridApi.isDestroyed() || !needle) return []
    const columns = gridApi.getAllDisplayedColumns().filter((column) => column.getColDef().context?.findable)
    const found: Match[] = []
    const visit = (node: IRowNode<Row>) => {
      if (!node.id) return
      for (const column of columns) {
        const value = gridApi.getCellValue({ rowNode: node, colKey: column, useFormatter: true })
        const count = occurrences(value === null || value === undefined ? "" : String(value), needle)
        for (let index = 0; index < count; index++) {
          found.push({ rowId: node.id, colId: column.getColId(), index, node })
        }
      }
    }
    for (let index = 0; index < gridApi.getPinnedTopRowCount(); index++) {
      const node = gridApi.getPinnedTopRow(index)
      if (node) visit(node)
    }
    gridApi.forEachNodeAfterFilterAndSort(visit)
    return found
  }, [gridApi, needle])

  // recount when the term changes and whenever the rows or columns on screen do
  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed()) return
    const recount = () => {
      const found = collect()
      setMatches(found)
      setPosition((was) => (found.length === 0 ? 0 : Math.min(was, found.length - 1)))
    }
    recount()
    const events = ["modelUpdated", "pinnedRowDataChanged", "displayedColumnsChanged", "cellValueChanged"] as const
    for (const name of events) gridApi.addEventListener(name, recount)
    return () => {
      if (gridApi.isDestroyed()) return
      for (const name of events) gridApi.removeEventListener(name, recount)
    }
  }, [gridApi, collect])

  // tell the cells what to mark
  const active = matches[position]
  useEffect(() => {
    publish({
      term: needle,
      active: active ? { rowId: active.rowId, colId: active.colId, index: active.index } : null,
    })
  }, [publish, needle, active])

  const reveal = useCallback(
    (match: Match | undefined) => {
      if (!match || !gridApi || gridApi.isDestroyed()) return
      if (!match.node.rowPinned) gridApi.ensureNodeVisible(match.node, "middle")
      gridApi.ensureColumnVisible(match.colId)
    },
    [gridApi]
  )

  const step = useCallback(
    (by: number) => {
      if (matches.length === 0) return
      const next = (position + by + matches.length) % matches.length
      setPosition(next)
      reveal(matches[next])
    },
    [matches, position, reveal]
  )

  const setTerm = useCallback((next: string) => {
    setTermState(next)
    setPosition(0)
  }, [])

  return {
    term,
    setTerm,
    store,
    count: matches.length,
    // 1-based, 0 when there is nothing
    current: matches.length === 0 ? 0 : position + 1,
    next: useCallback(() => step(1), [step]),
    previous: useCallback(() => step(-1), [step]),
  }
}
