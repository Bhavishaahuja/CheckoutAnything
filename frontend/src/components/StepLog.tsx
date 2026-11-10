// The live step log: one sentence per SSE event, newest at the bottom.

import { Check, FileJson2, Globe, LoaderCircle, PartyPopper, RefreshCw, TriangleAlert, X } from "lucide-react"
import { AnimatePresence } from "motion/react"
import { useEffect, useRef, type ReactNode } from "react"

import { AnimatedListItem } from "@/components/magicui/animated-list"
import type { StoreEvent } from "@/lib/types"
import { cn } from "@/lib/utils"

function iconFor(event: StoreEvent, isLast: boolean, running: boolean): { icon: ReactNode; tone: string } {
  const busy = isLast && running
  switch (event.type) {
    case "fetch.started":
    case "fetch.done":
      return { icon: busy ? <LoaderCircle className="spin-slow" /> : <Globe />, tone: "text-muted-foreground" }
    case "extract.started":
      return { icon: busy ? <LoaderCircle className="spin-slow" /> : <FileJson2 />, tone: "text-primary" }
    case "extract.done":
      return { icon: <FileJson2 />, tone: "text-primary" }
    case "item.checking":
      return { icon: busy ? <LoaderCircle className="spin-slow" /> : <Check />, tone: "text-muted-foreground" }
    case "item.verified":
      return { icon: <Check strokeWidth={3} />, tone: "text-ok" }
    case "item.failed":
      return { icon: <X strokeWidth={3} />, tone: "text-bad" }
    case "item.repairing":
      return { icon: <RefreshCw className={cn(busy && "spin-slow")} />, tone: "text-warn" }
    case "store.ready":
      return { icon: <PartyPopper />, tone: "text-ok" }
    default:
      return { icon: <TriangleAlert />, tone: "text-bad" }
  }
}

export function StepLog({
  events,
  running,
  selectedItemId,
  onPickItem,
}: {
  events: StoreEvent[]
  running: boolean
  selectedItemId: string | null
  onPickItem: (itemId: string) => void
}) {
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // stick to the bottom as new steps arrive
    const box = scroller.current
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" })
  }, [events.length])

  if (events.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-[13px] text-muted-foreground">
        Every step shows up here as it happens: the fetch, what Claude wrote, each page check and each PayPal
        sandbox order.
      </div>
    )
  }

  return (
    <div ref={scroller} className="calm-scroll h-full overflow-y-auto px-2 py-2" aria-live="polite">
      <div role="log" className="flex flex-col gap-0.5">
        <AnimatePresence initial={false}>
          {events.map((event, index) => {
            const look = iconFor(event, index === events.length - 1, running)
            const clickable = Boolean(event.item_id)
            return (
              <AnimatedListItem key={event.seq}>
                <div
                  className={cn(
                    "flex gap-2.5 rounded-md px-2 py-1.5 text-[13px] leading-snug",
                    clickable && "cursor-pointer hover:bg-muted",
                    event.item_id && event.item_id === selectedItemId && "bg-muted"
                  )}
                  onClick={() => event.item_id && onPickItem(event.item_id)}
                >
                  <span className={cn("mt-0.5 shrink-0 [&_svg]:size-3.5", look.tone)}>{look.icon}</span>
                  <span
                    className={cn(
                      "min-w-0 break-words",
                      event.type === "item.checking" && "text-muted-foreground",
                      (event.type === "store.ready" || event.type === "error") && "font-medium"
                    )}
                  >
                    {event.message}
                  </span>
                </div>
              </AnimatedListItem>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}
