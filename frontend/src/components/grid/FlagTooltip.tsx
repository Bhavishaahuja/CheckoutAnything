// The tooltip on a catalog cell. On a cell the agent was unsure about it says why, with the
// reasons the API worked out. On any other cell it is the plain full text.

import type { CustomTooltipProps } from "ag-grid-react"
import { TriangleAlert } from "lucide-react"
import { motion } from "motion/react"

import { POP } from "@/components/grid/motion"

import type { CatalogRow, FlagField } from "@/lib/types"

// the grid column each flagged spec field shows up in
export const FLAG_COLUMN: Record<FlagField, string> = {
  name: "name",
  unit_price: "unit_price",
  available: "status",
}

export function flagForColumn(row: CatalogRow | undefined, colId: string) {
  if (!row) return null
  for (const field of Object.keys(row.flags) as FlagField[]) {
    if (FLAG_COLUMN[field] === colId) return { field, ...row.flags[field]! }
  }
  return null
}

export function FlagTooltip(props: CustomTooltipProps<CatalogRow>) {
  const colId = props.column && "getColId" in props.column ? props.column.getColId() : ""
  const flag = props.location === "cell" ? flagForColumn(props.data, colId) : null

  if (!flag || flag.resolved) {
    if (!props.value) return null
    return (
      <div className="max-w-xs rounded-lg border border-border bg-card px-3 py-2 text-xs text-pretty shadow-lg">
        {String(props.value)}
      </div>
    )
  }
  return (
    <motion.div
      className="w-72 origin-top-left rounded-lg border border-border bg-card text-xs shadow-lg"
      initial={{ opacity: 0, scale: 0.94, y: -4 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={POP}
    >
      <div className="flex items-center gap-1.5 rounded-t-lg bg-warn-soft px-3 py-1.5 font-medium text-warn">
        <TriangleAlert className="size-3.5" aria-hidden /> Needs a look
      </div>
      <ul className="flex flex-col gap-1.5 px-3 py-2 text-pretty">
        {flag.reasons.map((reason, index) => (
          <motion.li key={reason} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.06 + index * 0.07 }}>
            {reason}
          </motion.li>
        ))}
      </ul>
      <div className="border-t border-border px-3 py-1.5 text-muted-foreground">
        Fix the value, or press the check if it is right.
      </div>
    </motion.div>
  )
}
