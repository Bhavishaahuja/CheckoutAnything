// Grid state save and restore: column widths, order, pinning, hidden columns, sort, filters
// and the page size survive a refresh. AG Grid's `initialState` puts them back and
// `onStateUpdated` writes every change to localStorage.

import type { GridState, StateUpdatedEvent } from "ag-grid-community"
import { useCallback, useMemo, useState } from "react"

const PREFIX = "checkout-anything.grid."

function readLayout(key: string): GridState | undefined {
  try {
    const raw = window.localStorage.getItem(PREFIX + key)
    if (!raw) return undefined
    const parsed = JSON.parse(raw) as GridState
    return parsed && typeof parsed === "object" ? parsed : undefined
  } catch {
    // storage blocked, or something else wrote junk there
    return undefined
  }
}

// only the layout is kept. selection, focus, scroll and the search box start fresh
function pickLayout(state: GridState): GridState {
  const layout: GridState = {
    columnSizing: state.columnSizing,
    columnOrder: state.columnOrder,
    columnPinning: state.columnPinning,
    columnVisibility: state.columnVisibility,
    sort: state.sort,
    filter: state.filter,
  }
  // the page size, but always open on the first page
  if (state.pagination) layout.pagination = { page: 0, pageSize: state.pagination.pageSize }
  return layout
}

export function useGridLayout(key: string) {
  // bumping this remounts the grid, which is how "Reset layout" gets back to the defaults
  const [layoutVersion, setLayoutVersion] = useState(0)
  const [hasSaved, setHasSaved] = useState(() => readLayout(key) !== undefined)

  // read once per mount of the grid, AG Grid only looks at initialState when it is created
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initialState = useMemo(() => readLayout(key), [key, layoutVersion])

  const onStateUpdated = useCallback(
    (event: StateUpdatedEvent) => {
      // the first event only reports the state the grid started with
      if (event.sources.length === 1 && event.sources[0] === "gridInitializing") return
      try {
        window.localStorage.setItem(PREFIX + key, JSON.stringify(pickLayout(event.state)))
        setHasSaved(true)
      } catch {
        // no storage, the layout just doesn't persist
      }
    },
    [key]
  )

  const resetLayout = useCallback(() => {
    try {
      window.localStorage.removeItem(PREFIX + key)
    } catch {
      // nothing was saved then
    }
    setHasSaved(false)
    setLayoutVersion((version) => version + 1)
  }, [key])

  return { initialState, onStateUpdated, resetLayout, layoutVersion, hasSaved }
}
