// A small "Columns" menu: show or hide columns. (AG Grid's own column chooser is the
// Enterprise tool panel, this one just calls setColumnsVisible.) The grid state hook saves
// whatever is picked here.

import type { GridApi } from "ag-grid-community"
import { Columns3, Link } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"

import { Button } from "@/components/ui/button"

interface Entry {
  colId: string
  label: string
  visible: boolean
  locked: boolean
  note: string | null
}

export function ColumnsMenu<Row>({
  gridApi,
  note,
}: {
  gridApi: GridApi<Row> | null
  // an extra line under a column's name, used for the PayPal field it maps to
  note?: (colId: string) => string | null
}) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<Entry[]>([])
  const wrapper = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!gridApi || gridApi.isDestroyed() || !open) return
    const read = () => {
      if (gridApi.isDestroyed()) return
      const next: Entry[] = []
      for (const column of gridApi.getColumns() || []) {
        const definition = column.getColDef()
        const label = gridApi.getDisplayNameForColumn(column, null)
        if (!label) continue // the drag handle and the row buttons have no name
        next.push({
          colId: column.getColId(),
          label,
          visible: column.isVisible(),
          locked: Boolean(definition.lockVisible),
          note: note ? note(column.getColId()) : null,
        })
      }
      setEntries(next)
    }
    read()
    gridApi.addEventListener("columnVisible", read)
    gridApi.addEventListener("newColumnsLoaded", read)
    return () => {
      if (gridApi.isDestroyed()) return
      gridApi.removeEventListener("columnVisible", read)
      gridApi.removeEventListener("newColumnsLoaded", read)
    }
  }, [gridApi, open, note])

  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("pointerdown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("pointerdown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  return (
    <div ref={wrapper} className="relative">
      <Button size="sm" variant="outline" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen((was) => !was)}>
        <Columns3 /> <span className="hidden sm:inline">Columns</span>
      </Button>
      {open && (
        <div
          id={menuId}
          role="group"
          aria-label="Show or hide columns"
          className="calm-scroll absolute top-full right-0 z-20 mt-1.5 max-h-80 w-64 overflow-y-auto rounded-xl border border-border bg-card p-1.5 shadow-lg"
        >
          {entries.map((entry) => (
            <label
              key={entry.colId}
              className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2 py-1.5 text-[13px] hover:bg-muted has-disabled:cursor-not-allowed has-disabled:opacity-60"
            >
              <input
                type="checkbox"
                checked={entry.visible}
                disabled={entry.locked}
                onChange={(event) => gridApi?.setColumnsVisible([entry.colId], event.target.checked)}
                className="mt-0.5 size-3.5 accent-(--primary)"
              />
              <span className="min-w-0">
                <span className="block truncate">{entry.label}</span>
                {entry.note && (
                  <span className="flex items-center gap-1 font-mono text-[10.5px] break-all text-muted-foreground">
                    <Link className="size-2.5 shrink-0" aria-hidden /> {entry.note}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
