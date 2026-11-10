// A column header the merchant can rename in place (double-click, the pencil, or F2 on the
// focused header). Enter saves, Escape cancels. AG Grid's own header editing is an Enterprise
// module, so this is a Community custom header component that keeps what the default header
// does: click to sort, the sort arrow, and the filter button.

import type { CustomHeaderProps } from "ag-grid-react"
import { ArrowUp, Link, ListFilter, Pencil } from "lucide-react"
import { motion } from "motion/react"
import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

export interface HeaderContext {
  // undefined when headers can't be renamed (the store is still connecting)
  renameColumn?: (colId: string, label: string) => Promise<void>
  // where a column's value goes in the PayPal order, if it goes there
  paypalField?: (colId: string) => string | null
}

export function EditableHeader(props: CustomHeaderProps<unknown, HeaderContext>) {
  const { column, displayName, enableSorting, enableFilterButton, progressSort, showFilter, eGridHeader, context } = props
  const colId = column.getColId()
  const [sort, setSort] = useState(column.getSort() ?? null)
  const [filtered, setFiltered] = useState(column.isFilterActive())
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(displayName)
  const [saving, setSaving] = useState(false)
  const filterButton = useRef<HTMLButtonElement>(null)
  const clickTimer = useRef<number | null>(null)
  const canRename = Boolean(context.renameColumn) && props.column.getColDef().context?.renameable !== false
  const paypalField = context.paypalField?.(colId) || null

  useEffect(() => {
    const onSort = () => setSort(column.getSort() ?? null)
    const onFilter = () => setFiltered(column.isFilterActive())
    column.addEventListener("sortChanged", onSort)
    column.addEventListener("filterChanged", onFilter)
    return () => {
      column.removeEventListener("sortChanged", onSort)
      column.removeEventListener("filterChanged", onFilter)
    }
  }, [column])

  // F2 on the focused header cell starts a rename, the same key that edits a cell
  useEffect(() => {
    if (!canRename) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "F2" && event.target === eGridHeader) {
        event.preventDefault()
        setDraft(displayName)
        setEditing(true)
      }
    }
    eGridHeader.addEventListener("keydown", onKey)
    return () => eGridHeader.removeEventListener("keydown", onKey)
  }, [canRename, displayName, eGridHeader])

  const startEdit = () => {
    if (!canRename) return
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current)
    setDraft(displayName)
    setEditing(true)
  }

  const commit = async () => {
    const label = draft.trim().replace(/\s+/g, " ")
    setEditing(false)
    if (label === displayName || !context.renameColumn) return
    setSaving(true)
    try {
      await context.renameColumn(colId, label)
    } finally {
      setSaving(false)
      eGridHeader.focus()
    }
  }

  if (editing) {
    return (
      <motion.input
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.14 }}
        autoFocus
        value={draft}
        maxLength={40}
        aria-label={"Rename the " + displayName + " column"}
        onFocus={(event) => event.target.select()}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(event) => {
          // the grid would move focus or sort on these
          event.stopPropagation()
          if (event.key === "Enter") void commit()
          if (event.key === "Escape") {
            setEditing(false)
            eGridHeader.focus()
          }
        }}
        onClick={(event) => event.stopPropagation()}
        className="h-7 w-full min-w-0 rounded-md border border-primary bg-card px-1.5 text-xs font-medium text-foreground outline-none"
      />
    )
  }

  const sortable = Boolean(enableSorting)
  return (
    <div className={cn("group/header flex w-full min-w-0 items-center gap-1", saving && "opacity-60")}>
      <span
        role={sortable ? "button" : undefined}
        title={canRename ? "Double-click to rename" : undefined}
        onClick={(event) => {
          if (!sortable) return
          // wait a beat, so a double-click renames instead of sorting twice
          const multi = event.shiftKey
          if (clickTimer.current !== null) window.clearTimeout(clickTimer.current)
          clickTimer.current = window.setTimeout(() => progressSort(multi), canRename ? 220 : 0)
        }}
        onDoubleClick={startEdit}
        className={cn("min-w-0 truncate", sortable && "cursor-pointer")}
      >
        {displayName}
      </span>
      {paypalField && (
        <span title={"Sent to PayPal as " + paypalField} className="shrink-0 text-muted-foreground/60">
          <Link className="size-3" aria-hidden />
          <span className="sr-only">Sent to PayPal as {paypalField}</span>
        </span>
      )}
      {sort && (
        // one arrow that turns over, instead of two that swap
        <motion.span className="flex shrink-0 text-foreground" initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: 1, scale: 1, rotate: sort === "desc" ? 180 : 0 }} aria-hidden>
          <ArrowUp className="size-3.5" />
        </motion.span>
      )}
      <span className="ml-auto flex shrink-0 items-center">
        {canRename && (
          <button
            type="button"
            tabIndex={-1}
            aria-label={"Rename the " + displayName + " column"}
            onClick={(event) => {
              event.stopPropagation()
              startEdit()
            }}
            className="hidden size-6 items-center justify-center rounded-md group-hover/header:flex hover:bg-muted"
          >
            <Pencil className="size-3" />
          </button>
        )}
        {enableFilterButton && (
          <button
            ref={filterButton}
            type="button"
            tabIndex={-1}
            aria-label={"Filter " + displayName}
            onClick={(event) => {
              event.stopPropagation()
              if (filterButton.current) showFilter(filterButton.current)
            }}
            className={cn(
              "size-6 items-center justify-center rounded-md hover:bg-muted",
              filtered ? "flex text-primary" : "hidden group-hover/header:flex"
            )}
          >
            <ListFilter className="size-3.5" />
          </button>
        )}
      </span>
    </div>
  )
}
