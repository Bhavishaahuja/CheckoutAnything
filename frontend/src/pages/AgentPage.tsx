// Screen 3: chat with the demo shopping agent and watch its tool calls.

import { ArrowUp, Bot, Check, ChevronRight, CreditCard, ListChecks, Search, Store as StoreIcon, TriangleAlert } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"

import { Card, CopyId, ErrorNote, Pill, Switch } from "@/components/bits"
import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text"
import { BlurFade } from "@/components/magicui/blur-fade"
import { Confetti, type ConfettiRef } from "@/components/magicui/confetti"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { money } from "@/lib/format"
import type { AgentReply, AgentStep, ChatMessage, Store } from "@/lib/types"
import { cn } from "@/lib/utils"

interface Turn {
  id: number
  question: string
  pending: boolean
  answer: AgentReply | null
  error: string | null
  // tool calls are revealed one at a time, this is how many are showing
  shown: number
}

const STEP_REVEAL_MS = 650

function text(value: unknown): string {
  if (value === null || value === undefined) return ""
  return String(value)
}

function StepCard({ step }: { step: AgentStep }) {
  const output = step.output || {}
  let icon: ReactNode = <ChevronRight />
  let summary: ReactNode = null

  if (step.tool === "list_stores") {
    icon = <StoreIcon />
    const found = Array.isArray(output.stores) ? (output.stores as { name: string; verified_items: number }[]) : []
    summary = (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">{found.length} live {found.length === 1 ? "store" : "stores"}</span>
        {found.map((store) => (
          <Pill key={store.name} tone="muted">
            {store.name} · {store.verified_items}
          </Pill>
        ))}
      </div>
    )
  } else if (step.tool === "search_catalog") {
    icon = <Search />
    const items = Array.isArray(output.items) ? (output.items as { name: string; unit_price: string }[]) : []
    const merchant = output.merchant as { name?: string; currency?: string } | undefined
    summary = (
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">
          {text(step.input.query) ? "“" + text(step.input.query) + "”" : "Everything"} at {merchant?.name || "store " + text(step.input.store_id)}:
        </span>
        {items.slice(0, 4).map((found) => (
          <Pill key={found.name} tone="muted">
            {found.name} · {money(found.unit_price, merchant?.currency)}
          </Pill>
        ))}
        {items.length > 4 && <span className="text-xs text-muted-foreground">+{items.length - 4} more</span>}
        {items.length === 0 && <span className="text-muted-foreground">nothing matched</span>}
      </div>
    )
  } else if (step.tool === "buy_item") {
    icon = <CreditCard />
    if (!step.is_error && output.status === "captured") {
      summary = (
        <div className="mt-1 rounded-lg border border-ok/30 bg-ok-soft px-3 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 font-medium text-ok">
              <Check className="size-4" strokeWidth={3} /> Payment captured
            </span>
            <span className="font-mono text-base font-semibold tabular-nums">
              {money(text(output.total), text(output.currency) || "USD")}
            </span>
          </div>
          <div className="mt-1 text-[13px]">
            {text(output.quantity) || "1"} × {text(output.bought)}
            {Number(output.shipping) > 0 && (
              <span className="text-muted-foreground"> · includes {money(text(output.shipping))} shipping</span>
            )}
          </div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <dt>PayPal order</dt>
            <dd>
              <CopyId value={text(output.paypal_order_id) || null} />
            </dd>
            <dt>Capture</dt>
            <dd>
              <CopyId value={text(output.capture_id) || null} />
            </dd>
          </dl>
        </div>
      )
    }
  } else if (step.tool === "check_payment") {
    icon = <ListChecks />
    summary = <span className="text-muted-foreground">PayPal says: {text(output.status) || "see details"}</span>
  }

  if (step.is_error) {
    icon = <TriangleAlert />
    summary = <span className="text-bad">{text(output.error) || "The tool call failed"}</span>
  }

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5 text-[13px]">
      <div className="flex items-center gap-2">
        <span className={cn("[&_svg]:size-3.5", step.is_error ? "text-bad" : "text-primary")}>{icon}</span>
        <code className="font-mono text-xs font-medium">{step.tool}</code>
        <code className="min-w-0 truncate font-mono text-xs text-muted-foreground">
          {Object.keys(step.input || {}).length > 0 ? JSON.stringify(step.input) : ""}
        </code>
      </div>
      {summary && <div className="mt-1.5">{summary}</div>}
      <details className="mt-1.5 text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none hover:text-foreground">Raw result</summary>
        <pre className="calm-scroll mt-1.5 max-h-56 overflow-auto rounded-md bg-muted/60 p-2 font-mono leading-relaxed">
          {JSON.stringify(step.output, null, 2)}
        </pre>
      </details>
    </div>
  )
}

export function AgentPage({
  stores,
  claudeReady,
  checkReady,
  onOrdersChanged,
  onGoToConnect,
}: {
  stores: Store[]
  claudeReady: boolean
  // Check is on (CHECK_URL), which the sloppy demo toggle needs
  checkReady: boolean
  onOrdersChanged: () => void
  onGoToConnect: () => void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState("")
  // demo only, off by default. the API refuses it unless Check is there to hold the order
  const [sloppy, setSloppy] = useState(false)
  const nextId = useRef(1)
  const scroller = useRef<HTMLDivElement>(null)
  const confetti = useRef<ConfettiRef>(null)

  const liveStores = stores.filter((store) => store.status === "live")
  const busy = turns.some((turn) => turn.pending || (turn.answer !== null && turn.shown < turn.answer.steps.length))

  const suggestions = ["Get me a half sourdough loaf, sliced, from Hollowbrook Bakery."]
  for (const store of liveStores) {
    if (!store.merchant_name.includes("Hollowbrook")) suggestions.push("What can I buy at " + store.merchant_name + "?")
  }

  // reveal the tool calls of the newest answer one by one
  useEffect(() => {
    const waiting = turns.find((turn) => turn.answer !== null && turn.shown < turn.answer.steps.length)
    if (!waiting) return
    const timer = setTimeout(() => {
      setTurns((current) => current.map((turn) => (turn.id === waiting.id ? { ...turn, shown: turn.shown + 1 } : turn)))
      const step = waiting.answer!.steps[waiting.shown]
      if (step.tool === "buy_item" && !step.is_error && step.output.status === "captured") {
        void confetti.current?.fire({ particleCount: 70, spread: 75, origin: { y: 0.75 }, scalar: 0.9 })
        onOrdersChanged()
      }
    }, STEP_REVEAL_MS)
    return () => clearTimeout(timer)
  }, [turns, onOrdersChanged])

  useEffect(() => {
    const box = scroller.current
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" })
  }, [turns])

  const send = async (question: string) => {
    const cleaned = question.trim()
    if (!cleaned || busy) return
    setDraft("")

    // the API wants the whole conversation as user and assistant text, plus the ids of the
    // orders each answer placed so the agent remembers what it really bought
    const history: ChatMessage[] = []
    for (const turn of turns) {
      if (!turn.answer || !turn.answer.reply) continue
      const orderIds: number[] = []
      for (const order of turn.answer.orders) orderIds.push(order.id)
      history.push({ role: "user", content: turn.question })
      history.push({ role: "assistant", content: turn.answer.reply, order_ids: orderIds })
    }
    history.push({ role: "user", content: cleaned })

    const id = nextId.current++
    setTurns((current) => [...current, { id, question: cleaned, pending: true, answer: null, error: null, shown: 0 }])
    try {
      const answer = await api.agentChat(history, sloppy && checkReady)
      setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, pending: false, answer } : turn)))
    } catch (problem) {
      const message = problem instanceof Error ? problem.message : "The agent call failed"
      setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, pending: false, error: message } : turn)))
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void send(draft)
  }

  return (
    <div className="mx-auto grid max-w-[1400px] gap-5 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_300px]">
      <Confetti ref={confetti} manualstart className="pointer-events-none fixed inset-0 z-50 size-full" />

      <Card className="flex h-[calc(100dvh-7.5rem)] min-h-[480px] flex-col overflow-hidden">
        <div className="flex h-12 shrink-0 items-center gap-2.5 border-b border-border px-4">
          <Bot className="size-4 text-primary" />
          <h1 className="text-sm font-semibold">Shopping agent</h1>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            A Claude agent with tools: list_stores, search_catalog, buy_item
          </span>
        </div>

        <div ref={scroller} className="calm-scroll min-h-0 flex-1 overflow-y-auto px-4 py-5">
          {turns.length === 0 && (
            <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-info-soft text-primary">
                <Bot className="size-5" />
              </div>
              <h2 className="mt-4 text-lg font-semibold">Send an agent shopping</h2>
              <p className="mt-1.5 text-sm text-pretty text-muted-foreground">
                It can only buy verified items from stores you connected. It pays with a saved sandbox buyer, so there
                is no popup, and the API sets the price.
              </p>
              {liveStores.length === 0 ? (
                <Button variant="outline" className="mt-5" onClick={onGoToConnect}>
                  Connect a store first
                </Button>
              ) : (
                <div className="mt-5 flex flex-col gap-2">
                  {suggestions.slice(0, 3).map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => void send(suggestion)}
                      className="rounded-lg border border-border px-3.5 py-2.5 text-left text-[13px] transition-colors hover:border-primary hover:bg-info-soft"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="mx-auto flex max-w-2xl flex-col gap-6">
            {turns.map((turn) => {
              const steps = turn.answer ? turn.answer.steps.slice(0, turn.shown) : []
              const revealed = turn.answer !== null && turn.shown >= turn.answer.steps.length
              return (
                <div key={turn.id} className="flex flex-col gap-3">
                  <div className="max-w-[85%] self-end rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                    {turn.question}
                  </div>

                  {steps.length > 0 && (
                    <div className="flex flex-col gap-2 border-l-2 border-border pl-3">
                      {steps.map((step, index) => (
                        <BlurFade key={index} duration={0.3} offset={8}>
                          <StepCard step={step} />
                        </BlurFade>
                      ))}
                    </div>
                  )}

                  {(turn.pending || (turn.answer && !revealed)) && (
                    <div className="text-[13px]">
                      <AnimatedShinyText className="mx-0">
                        {turn.pending ? "The agent is working, this takes a few seconds" : "Running tools"}
                      </AnimatedShinyText>
                    </div>
                  )}

                  {turn.error && <ErrorNote>{turn.error}</ErrorNote>}

                  {revealed && turn.answer!.reply && (
                    <BlurFade duration={0.35} offset={8}>
                      <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-muted px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
                        {turn.answer!.reply}
                      </div>
                    </BlurFade>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <form onSubmit={onSubmit} className="shrink-0 border-t border-border p-3">
          {!claudeReady && (
            <p className="mb-2 text-xs text-warn">ANTHROPIC_API_KEY isn't set on the API, so the agent can't answer yet.</p>
          )}
          <div className="mx-auto mb-2 flex max-w-2xl flex-wrap items-center gap-x-3 gap-y-1">
            <Pill tone="warn">DEMO</Pill>
            <Switch checked={sloppy && checkReady} onChange={setSloppy} label="Sloppy agent (demo)" disabled={!checkReady} />
            <span className="text-xs text-muted-foreground">
              {checkReady
                ? "Swaps in the next size over to show Check catching it"
                : "Needs Check (CHECK_URL) on the API, so the wrong order gets held"}
            </span>
          </div>
          <div className="mx-auto flex max-w-2xl items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5 focus-within:border-primary">
            <label className="sr-only" htmlFor="agent-input">
              Message the shopping agent
            </label>
            <input
              id="agent-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask the agent to buy something"
              maxLength={4000}
              className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
              autoComplete="off"
            />
            <Button type="submit" size="icon" disabled={busy || !draft.trim()} aria-label="Send" className="size-8 rounded-lg">
              <ArrowUp />
            </Button>
          </div>
        </form>
      </Card>

      <aside className="flex flex-col gap-3">
        <Card className="p-4">
          <h2 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Stores it can buy from</h2>
          {liveStores.length === 0 ? (
            <p className="mt-3 text-[13px] text-muted-foreground">
              None yet. A store shows up here once at least one item is verified.
            </p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2.5">
              {liveStores.map((store) => (
                <li key={store.id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="size-2 shrink-0 rounded-full bg-ok" />
                    <span className="truncate font-medium">{store.merchant_name}</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{store.counts.verified} items</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-4 text-[13px]">
          <h2 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Why this is safe</h2>
          <ul className="mt-3 flex flex-col gap-2 text-muted-foreground">
            <li>Claude only writes spec JSON. It never writes code that runs.</li>
            <li>Fixed, tested code makes every PayPal call.</li>
            <li>The total comes from the verified spec, never from the agent.</li>
            <li>Sandbox only. No real money moves.</li>
          </ul>
        </Card>
      </aside>
    </div>
  )
}
