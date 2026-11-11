// The review drawer for an order on hold. It never approves or rejects anything itself: it
// asks the API for a review link (behind the merchant's login) and shows the real Check
// confirm page for that link in an iframe. The decision is made on that page, so Check records
// when it was opened and how long the decision took exactly as it does on the buyer's phone.
// When the page says a decision was made, the drawer tells the grid and closes.

import { LockKeyhole, X } from "lucide-react"
import { motion } from "motion/react"
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { CopyId, ErrorNote } from "@/components/bits"
import { Button } from "@/components/ui/button"
import { api, ApiError } from "@/lib/api"
import type { Order, ReviewLink } from "@/lib/types"

// what the confirm page posts to its parent window (check/frontend/src/lib/parentMessage.ts)
const MESSAGE_SOURCE = "checkout-anything-check"
const DECIDED = "review-decided"
// long enough to read "Approved" on the confirm page before the drawer goes
const CLOSE_AFTER_MS = 1600

type Phase =
  | { kind: "login"; message: string | null }
  | { kind: "loading" }
  | { kind: "ready"; link: ReviewLink }
  | { kind: "failed"; message: string }

// the confirm page reads ?theme= before it paints (check/frontend/index.html), so the page in the
// drawer wears this app's theme. only the framed copy, the buyer's link below stays as it is
function inThisTheme(url: string): string {
  try {
    const framed = new URL(url)
    framed.searchParams.set("theme", document.documentElement.classList.contains("dark") ? "dark" : "light")
    return framed.toString()
  } catch {
    return url
  }
}

function originOf(url: string): string | null {
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

export function ReviewDrawer({
  order,
  onClose,
  onDecided,
}: {
  order: Order
  onClose: () => void
  // the confirm page finished a decision: refresh the row now, the drawer closes by itself
  onDecided: () => void
}) {
  const [phase, setPhase] = useState<Phase>(() => (api.hasSession() ? { kind: "loading" } : { kind: "login", message: null }))
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const frame = useRef<HTMLIFrameElement>(null)
  const asked = useRef(false)
  const orderId = order.id

  // one link per time the drawer opens: asking again would kill the link already on screen
  const askForLink = useCallback(async () => {
    setPhase({ kind: "loading" })
    try {
      const link = await api.reviewLink(orderId)
      setPhase({ kind: "ready", link })
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 401) {
        setPhase({ kind: "login", message: api.hasSession() ? null : problem.message })
      } else {
        setPhase({ kind: "failed", message: problem instanceof Error ? problem.message : "Couldn't open the review" })
      }
    }
  }, [orderId])

  useEffect(() => {
    // the ref stops React's dev double-run from making (and so killing) two links
    if (asked.current || !api.hasSession()) return
    asked.current = true
    void askForLink()
  }, [askForLink])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const link = phase.kind === "ready" ? phase.link : null
  useEffect(() => {
    if (!link) return
    const allowed = originOf(link.url)
    let closing: ReturnType<typeof setTimeout> | null = null
    const onMessage = (event: MessageEvent) => {
      // only the confirm page we framed, from the Check frontend's own origin
      if (event.origin !== allowed || event.source !== frame.current?.contentWindow) return
      const data = event.data as { source?: unknown; type?: unknown } | null
      if (!data || data.source !== MESSAGE_SOURCE || data.type !== DECIDED) return
      if (closing !== null) return
      onDecided()
      closing = setTimeout(onClose, CLOSE_AFTER_MS)
    }
    window.addEventListener("message", onMessage)
    return () => {
      window.removeEventListener("message", onMessage)
      if (closing !== null) clearTimeout(closing)
    }
  }, [link, onClose, onDecided])

  const logIn = async (event: FormEvent) => {
    event.preventDefault()
    if (!password || busy) return
    setBusy(true)
    try {
      await api.logIn(password)
      setPassword("")
      asked.current = true
      await askForLink()
    } catch (problem) {
      setPhase({ kind: "login", message: problem instanceof Error ? problem.message : "Couldn't log in" })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label={"Review order " + order.id}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-border bg-card shadow-2xl"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", stiffness: 420, damping: 40 }}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold tracking-tight">Review order {order.id}</h2>
            <p className="truncate text-xs text-muted-foreground">
              {order.description}
              {order.store_name ? " at " + order.store_name : ""}
            </p>
          </div>
          <Button variant="ghost" className="size-11" onClick={onClose} aria-label="Close review">
            <X />
          </Button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col">
          {phase.kind === "login" && (
            <form onSubmit={logIn} className="flex flex-col gap-3 p-5">
              <span className="flex size-10 items-center justify-center rounded-full bg-info-soft text-primary">
                <LockKeyhole className="size-5" />
              </span>
              <div>
                <h3 className="text-sm font-semibold">Log in to review</h3>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  Reviewing can release or cancel a payment, so it needs the merchant password. It is the same one
                  as the Check dashboard.
                </p>
              </div>
              {phase.message && <ErrorNote>{phase.message}</ErrorNote>}
              <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="h-11 rounded-lg border border-border bg-background px-3 text-sm font-normal outline-none focus-visible:border-primary"
                />
              </label>
              <Button type="submit" size="lg" disabled={!password || busy}>
                {busy ? "Logging in..." : "Log in and review"}
              </Button>
            </form>
          )}

          {phase.kind === "loading" && <p className="p-5 text-[13px] text-muted-foreground">Opening the review...</p>}

          {phase.kind === "failed" && (
            <div className="flex flex-col gap-3 p-5">
              <ErrorNote>{phase.message}</ErrorNote>
              <Button variant="outline" size="lg" onClick={() => void askForLink()}>
                Try again
              </Button>
            </div>
          )}

          {phase.kind === "ready" && (
            <>
              <iframe
                ref={frame}
                src={inThisTheme(phase.link.url)}
                title={"Confirm page for order " + order.id}
                className="min-h-0 w-full flex-1 border-0 bg-background"
                referrerPolicy="no-referrer"
              />
              <footer className="flex shrink-0 items-center gap-2 border-t border-border px-4 py-2 text-xs text-muted-foreground">
                <span className="shrink-0">Buyer's link</span>
                <CopyId value={phase.link.url} className="min-h-11 min-w-0 flex-1" />
              </footer>
            </>
          )}
        </div>
      </motion.aside>
    </>
  )
}
