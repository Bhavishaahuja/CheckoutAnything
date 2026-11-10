// The price cell's editor. Blank, negative, zero and non-numeric input shows what is wrong
// right under the field, and can't be saved: Enter and Tab are held back while it is wrong,
// and clicking away cancels the edit instead of committing it.

import { useGridCellEditor, type CustomCellEditorProps } from "ag-grid-react"
import { animate } from "motion"
import { useCallback, useEffect, useId, useRef, useState } from "react"

import { normalizePrice, priceError } from "@/lib/price"

export function PriceEditor({ value, onValueChange, eventKey }: CustomCellEditorProps<unknown, string>) {
  // typing a digit on the cell starts the edit with that digit, like a spreadsheet
  const startedWith = eventKey && /^[\d.]$/.test(eventKey) ? eventKey : null
  const [text, setText] = useState(startedWith ?? value ?? "")
  const textRef = useRef(text)
  const input = useRef<HTMLInputElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const errorId = useId()
  const error = priceError(text)

  useEffect(() => {
    const element = input.current
    if (!element) return
    element.focus()
    if (startedWith === null) element.select()
    else element.setSelectionRange(element.value.length, element.value.length)
  }, [startedWith])

  // Enter and Tab don't get through while the price is wrong. A native listener on the input
  // itself: the grid listens further up, and React's own handler would run after it
  useEffect(() => {
    const element = input.current
    if (!element) return
    const onKey = (event: KeyboardEvent) => {
      if ((event.key !== "Enter" && event.key !== "Tab") || priceError(textRef.current) === null) return
      event.preventDefault()
      event.stopPropagation()
      if (box.current && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        animate(box.current, { x: [0, -4, 4, -2, 2, 0] }, { duration: 0.3 })
      }
    }
    element.addEventListener("keydown", onKey)
    return () => element.removeEventListener("keydown", onKey)
  }, [])

  // the grid asks this when the edit ends. true throws the edit away
  const isCancelAfterEnd = useCallback(() => priceError(textRef.current) !== null, [])
  useGridCellEditor({ isCancelAfterEnd })

  const change = (next: string) => {
    textRef.current = next
    setText(next)
    onValueChange(priceError(next) === null ? normalizePrice(next) : next)
  }

  return (
    <div ref={box} className="w-44 rounded-lg bg-card p-1.5">
      <label className="flex h-8 items-center gap-1 rounded-md border px-2 font-mono text-[13px] tabular-nums"
        style={{ borderColor: error ? "var(--bad)" : "var(--primary)" }}>
        <span className="text-muted-foreground" aria-hidden>
          $
        </span>
        <span className="sr-only">Price</span>
        <input
          ref={input}
          value={text}
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={error !== null}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => change(event.target.value)}
          className="w-full min-w-0 bg-transparent outline-none"
        />
      </label>
      <p id={errorId} role="alert" className="min-h-4 px-1 pt-1 text-[11px] leading-4 text-bad">
        {error}
      </p>
    </div>
  )
}
