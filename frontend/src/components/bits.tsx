// Small shared pieces: status pills, check marks, a switch, copyable ids.

import { Check, CircleDashed, Copy, LoaderCircle, Minus, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { useState, type ReactNode } from "react"

import type { CheckState, RowStatus, StoreStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const PILL_TONES = {
  ok: "bg-ok-soft text-ok",
  bad: "bg-bad-soft text-bad",
  warn: "bg-warn-soft text-warn",
  info: "bg-info-soft text-primary",
  muted: "bg-muted text-muted-foreground",
}

export function Pill({
  tone,
  children,
  className,
}: {
  tone: keyof typeof PILL_TONES
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs leading-none font-medium whitespace-nowrap",
        PILL_TONES[tone],
        className
      )}
    >
      {children}
    </span>
  )
}

function rowStatusLook(status: RowStatus): { tone: keyof typeof PILL_TONES; icon: ReactNode; label: string } {
  if (status === "verified") return { tone: "ok", icon: <DrawnCheck className="size-3.5" />, label: "Verified" }
  if (status === "failed") return { tone: "bad", icon: <X className="size-3.5" strokeWidth={3} />, label: "Failed" }
  if (status === "repairing") return { tone: "warn", icon: <LoaderCircle className="spin-slow size-3.5" />, label: "Repairing" }
  if (status === "unavailable") return { tone: "muted", icon: <Minus className="size-3.5" />, label: "Not for sale" }
  return { tone: "info", icon: <LoaderCircle className="spin-slow size-3.5" />, label: "Checking" }
}

// a check mark that draws itself (Motion animates the SVG path length)
function DrawnCheck({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <motion.path
        d="M5 12.5l4.5 4.5L19 7.5"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.35, ease: "easeOut", delay: 0.1 }}
      />
    </svg>
  )
}

// the pill springs in each time the status changes
export function RowStatusPill({ status }: { status: RowStatus }) {
  const look = rowStatusLook(status)
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span
        key={status}
        className="inline-flex"
        initial={{ opacity: 0, scale: 0.7, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.85, y: -6 }}
        transition={{ type: "spring", stiffness: 520, damping: 26 }}
      >
        <Pill tone={look.tone}>
          {look.icon} {look.label}
        </Pill>
      </motion.span>
    </AnimatePresence>
  )
}

export function StoreStatusPill({ status }: { status: StoreStatus | "idle" }) {
  if (status === "live") {
    return (
      <Pill tone="ok">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-ok" />
        </span>
        Agent-ready
      </Pill>
    )
  }
  if (status === "failed") return <Pill tone="bad">Not live</Pill>
  if (status === "connecting") {
    return (
      <Pill tone="info">
        <LoaderCircle className="spin-slow size-3.5" /> Connecting
      </Pill>
    )
  }
  return null
}

export function CheckMark({ state, label }: { state: CheckState; label: string }) {
  let icon = <CircleDashed className="size-4 text-muted-foreground/60" />
  let text = "waiting"
  if (state === "running") {
    icon = <LoaderCircle className="spin-slow size-4 text-primary" />
    text = "running"
  }
  if (state === "ok") {
    icon = (
      <span className="flex size-5 items-center justify-center rounded-full bg-ok-soft text-ok">
        <DrawnCheck className="size-3.5" />
      </span>
    )
    text = "passed"
  }
  if (state === "fail") {
    icon = (
      <span className="flex size-5 items-center justify-center rounded-full bg-bad-soft text-bad">
        <X className="size-3.5" strokeWidth={3} />
      </span>
    )
    text = "failed"
  }
  if (state === "skipped") {
    icon = <Minus className="size-4 text-muted-foreground/60" />
    text = "not run"
  }
  // the mark pops in with a spring whenever the state changes
  return (
    <span className="inline-flex size-5 items-center justify-center" role="img" aria-label={label + " " + text} title={label + " " + text}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={state}
          className="inline-flex"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0, opacity: 0 }}
          transition={{ type: "spring", stiffness: 600, damping: 22 }}
        >
          {icon}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
  compact,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
  // hide the text on phones (the switch keeps its accessible name)
  compact?: boolean
}) {
  return (
    <label className={cn("inline-flex items-center gap-2 text-[13px] select-none", disabled && "opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors",
          checked ? "bg-primary" : "bg-border"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow-sm transition-transform",
            checked && "translate-x-4"
          )}
        />
      </button>
      <span className={cn("text-muted-foreground", compact && "hidden sm:inline")}>{label}</span>
    </label>
  )
}

export function CopyId({ value, className }: { value: string | null; className?: string }) {
  const [copied, setCopied] = useState(false)
  if (!value) return <span className="text-muted-foreground/60">-</span>
  return (
    <button
      type="button"
      title="Copy"
      onClick={(event) => {
        event.stopPropagation()
        void navigator.clipboard?.writeText(value)
        setCopied(true)
        setTimeout(() => setCopied(false), 1200)
      }}
      className={cn(
        "group inline-flex max-w-full items-center gap-1.5 font-mono text-xs text-muted-foreground hover:text-foreground",
        className
      )}
    >
      <span className="truncate">{value}</span>
      {copied ? (
        <Check className="size-3 shrink-0 text-ok" />
      ) : (
        <Copy className="size-3 shrink-0 opacity-0 group-hover:opacity-100" />
      )}
    </button>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("relative rounded-xl border border-border bg-card", className)}>{children}</div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">
      {children}
    </p>
  )
}
