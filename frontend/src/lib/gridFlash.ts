// Row feedback for the grids: AG Grid flash plus Motion.
//
//   AG Grid  api.flashCells() washes the whole row in a colour and fades it out. The colour
//            comes from a CSS variable, so we set it per row (green, red or blue) first.
//   Motion   animate() + stagger() run a quick wave across the row's cells, left to right,
//            so the eye follows the row that just changed.

import type { GridApi } from "ag-grid-community"
import { animate, stagger } from "motion"

export type FlashTone = "ok" | "bad" | "new"

const TONE_VARIABLE: Record<FlashTone, string> = {
  ok: "--ok",
  bad: "--bad",
  new: "--primary",
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

function findRowElements(container: HTMLElement, rowId: string) {
  // pinned columns would give more than one element per row, so take them all
  return container.querySelectorAll<HTMLElement>('.ag-row[row-id="' + CSS.escape(rowId) + '"]')
}

export function flashGridRow<Row>(api: GridApi<Row>, container: HTMLElement | null, rowId: string, tone: FlashTone) {
  if (api.isDestroyed()) return
  const node = api.getRowNode(rowId)
  if (!node) return

  // wait a frame so a row that was only just added is in the DOM
  requestAnimationFrame(() => {
    if (api.isDestroyed()) return
    const cells: HTMLElement[] = []
    if (container) {
      for (const rowElement of findRowElements(container, rowId)) {
        rowElement.style.setProperty(
          "--ag-value-change-value-highlight-background-color",
          "color-mix(in srgb, var(" + TONE_VARIABLE[tone] + ") 26%, transparent)"
        )
        for (const cell of rowElement.querySelectorAll<HTMLElement>(".ag-cell")) cells.push(cell)
      }
    }

    api.flashCells({ rowNodes: [node], flashDuration: 450, fadeDuration: 1100 })

    if (cells.length === 0 || prefersReducedMotion()) return
    if (tone === "bad") {
      // a short shake, the "no" gesture
      animate(cells, { x: [0, -5, 5, -3, 3, 0] }, { duration: 0.45, ease: "easeInOut" })
    } else if (tone === "ok") {
      // each cell lifts a little, one after the other
      animate(cells, { y: [0, -3, 0], scale: [1, 1.03, 1] }, { duration: 0.42, delay: stagger(0.045), ease: "easeOut" })
    } else {
      // a new row slides in cell by cell
      animate(cells, { opacity: [0, 1], x: [-10, 0] }, { duration: 0.32, delay: stagger(0.035), ease: "easeOut" })
    }
  })
}
