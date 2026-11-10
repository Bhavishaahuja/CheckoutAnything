// Custom overlays for both grids, so a grid is never just blank: what is loading (with
// progress), why it is empty (with something to do about it), or that a filter hides
// everything (with a way out).
//
// AG Grid mounts this one component for its loading, no-rows and no-matching-rows overlays
// (`overlayComponent`). What to say lives in a small store on the grid's context, so the
// text and the progress bar update while the overlay stays up.

import type { CustomOverlayProps } from "ag-grid-react"
import { LoaderCircle, SearchX } from "lucide-react"
import { motion } from "motion/react"
import { useSyncExternalStore, type ReactNode } from "react"

import { Press, Rise, SOFT } from "@/components/grid/motion"
import { Button } from "@/components/ui/button"

export interface OverlayContent {
  loading: {
    title: string
    // the step in progress, "Claude is writing the store spec"
    step?: string
    // 0 to 1, leave out when there is nothing to measure
    progress?: number
  }
  empty: {
    icon?: ReactNode
    title: string
    hint?: string
    actionLabel?: string
    onAction?: () => void
    busy?: boolean
  }
  // when a filter or search leaves no rows
  noMatch: {
    title: string
    actionLabel: string
    onAction: () => void
  }
}

export interface OverlayStore {
  get: () => OverlayContent
  set: (content: OverlayContent) => void
  subscribe: (listener: () => void) => () => void
}

export function createOverlayStore(initial: OverlayContent): OverlayStore {
  let content = initial
  const listeners = new Set<() => void>()
  return {
    get: () => content,
    set: (next) => {
      content = next
      for (const listener of listeners) listener()
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

export function GridOverlay(props: CustomOverlayProps<unknown, { overlay: OverlayStore }>) {
  const store = props.context.overlay
  const content = useSyncExternalStore(store.subscribe, store.get)

  if (props.overlayType === "loading") {
    const { title, step, progress } = content.loading
    return (
      <Rise className="pointer-events-auto flex w-72 max-w-full flex-col items-center gap-3 px-4 text-center">
        <span role="status" aria-live="polite" className="sr-only">
          {title}. {step}
        </span>
        <LoaderCircle className="spin-slow size-5 text-primary" aria-hidden />
        <div className="text-sm font-medium">{title}</div>
        {progress !== undefined && (
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            aria-label={title}
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          >
            {/* the bar springs to each step instead of jumping */}
            <motion.div
              className="h-full rounded-full bg-primary"
              initial={{ width: "4%" }}
              animate={{ width: Math.max(4, Math.round(progress * 100)) + "%" }}
              transition={SOFT}
            />
          </div>
        )}
        {step && (
          <motion.div key={step} className="text-xs text-muted-foreground" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={SOFT}>
            {step}
          </motion.div>
        )}
      </Rise>
    )
  }

  if (props.overlayType === "noMatchingRows") {
    const { title, actionLabel, onAction } = content.noMatch
    return (
      <Rise className="pointer-events-auto flex flex-col items-center gap-3 px-4 text-center">
        <SearchX className="size-5 text-muted-foreground" aria-hidden />
        <div className="text-sm font-medium">{title}</div>
        <Press>
          <Button size="sm" variant="outline" onClick={onAction}>
            {actionLabel}
          </Button>
        </Press>
      </Rise>
    )
  }

  if (props.overlayType === "exporting") {
    return (
      <div role="status" className="text-sm text-muted-foreground">
        Writing the file...
      </div>
    )
  }

  const { icon, title, hint, actionLabel, onAction, busy } = content.empty
  return (
    <div className="pointer-events-auto flex max-w-sm flex-col items-center gap-2 px-4 text-center">
      {/* the pieces arrive one after the other */}
      {icon && (
        <motion.div
          className="mb-1 text-muted-foreground [&_svg]:size-6"
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1, y: [0, -3, 0] }}
          transition={{ ...SOFT, y: { duration: 2.6, repeat: Infinity, ease: "easeInOut" } }}
        >
          {icon}
        </motion.div>
      )}
      <Rise delay={0.05} className="text-sm font-medium">
        {title}
      </Rise>
      {hint && (
        <Rise delay={0.1} className="text-[13px] text-pretty text-muted-foreground">
          {hint}
        </Rise>
      )}
      {actionLabel && onAction && (
        <Rise delay={0.16} className="mt-2">
          <Press disabled={busy}>
            <Button size="sm" onClick={onAction} disabled={busy}>
              {busy && <LoaderCircle className="spin-slow" />}
              {actionLabel}
            </Button>
          </Press>
        </Rise>
      )}
    </div>
  )
}
