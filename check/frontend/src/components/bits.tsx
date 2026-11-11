// copied from frontend/src/components/bits.tsx (Pill, Switch, CopyId, Card and ErrorNote only,
// the rest needs the main app's types), keep in sync

// Small shared pieces: status pills, a switch, copyable ids, cards and error notes.

import { Check, Copy } from "lucide-react"
import { useState, type ReactNode } from "react"

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
