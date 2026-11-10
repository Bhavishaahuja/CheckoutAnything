import { Bot, FlaskConical, Link2, ReceiptText, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useState, type ReactNode } from "react"

import { Pill, Switch } from "@/components/bits"
import { AnimatedThemeToggler } from "@/components/magicui/animated-theme-toggler"
import { Button } from "@/components/ui/button"
import { api, USE_MOCK } from "@/lib/api"
import type { AppConfig, Mode, Store } from "@/lib/types"
import { cn } from "@/lib/utils"
import { AgentPage } from "@/pages/AgentPage"
import { ConnectPage } from "@/pages/ConnectPage"
import { OrdersPage } from "@/pages/OrdersPage"

type Tab = "connect" | "agent" | "orders"

const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: "connect", label: "Connect", icon: <Link2 /> },
  { id: "agent", label: "Agent", icon: <Bot /> },
  { id: "orders", label: "Orders", icon: <ReceiptText /> },
]

function tabFromHash(): Tab {
  const wanted = window.location.hash.replace("#", "")
  for (const tab of TABS) {
    if (tab.id === wanted) return tab.id
  }
  return "connect"
}

function ResetButton({ mode, onDone, onError }: { mode: Mode; onDone: (firstStoreId: number | null) => void; onError: (message: string) => void }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  const reset = async () => {
    setBusy(true)
    try {
      const result = await api.resetDemo(mode)
      onDone(result.stores.length > 0 ? result.stores[0].store_id : null)
    } catch (problem) {
      onError(problem instanceof Error ? problem.message : "The reset failed")
    } finally {
      setBusy(false)
      setAsking(false)
    }
  }

  // an inline confirm, not a browser alert
  if (asking) {
    return (
      <span className="flex items-center gap-1.5 text-[13px]">
        <span className="hidden text-muted-foreground sm:inline">Wipe stores and orders?</span>
        <Button size="sm" variant="danger" onClick={reset} disabled={busy}>
          {busy ? "Resetting" : "Yes, reset"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAsking(false)} disabled={busy}>
          Cancel
        </Button>
      </span>
    )
  }
  return (
    <Button size="sm" variant="outline" onClick={() => setAsking(true)} aria-label="Reset demo">
      <RotateCcw /> <span className="hidden sm:inline">Reset demo</span>
    </Button>
  )
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [mode, setMode] = useState<Mode>("live")
  const [stores, setStores] = useState<Store[]>([])
  const [activeStoreId, setActiveStoreId] = useState<number | null>(null)
  const [ordersKey, setOrdersKey] = useState(0)
  const [banner, setBanner] = useState<string | null>(null)

  const goTo = useCallback((next: Tab) => {
    window.location.hash = next
    setTab(next)
  }, [])

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  const refreshStores = useCallback(() => {
    api
      .listStores()
      .then((list) => {
        setStores(list)
        setBanner(null)
      })
      .catch((problem) => setBanner(problem instanceof Error ? problem.message : "Can't reach the API"))
  }, [])

  const goToAgent = useCallback(() => goTo("agent"), [goTo])
  const bumpOrders = useCallback(() => setOrdersKey((key) => key + 1), [])

  useEffect(() => {
    api
      .getConfig()
      .then((loaded) => {
        setConfig(loaded)
        setMode(loaded.default_mode)
      })
      .catch((problem) => setBanner(problem instanceof Error ? problem.message : "Can't reach the API"))
    api
      .listStores()
      .then((list) => {
        setStores(list)
        // open on the newest store, so a reload lands where you were
        if (list.length > 0) setActiveStoreId(list[list.length - 1].id)
      })
      .catch(() => {})
  }, [])

  // while something is connecting, keep the store chips fresh
  const anyConnecting = stores.some((store) => store.status === "connecting")
  useEffect(() => {
    if (!anyConnecting) return
    const timer = setInterval(refreshStores, 2500)
    return () => clearInterval(timer)
  }, [anyConnecting, refreshStores])

  const missing: string[] = []
  if (config && !config.paypal_configured) missing.push("PayPal sandbox keys")
  if (config && !config.claude_configured) missing.push("the Claude API key")
  if (config && !config.vault_configured) missing.push("the saved buyer (vault id)")

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-2 px-4 sm:gap-3">
          <button type="button" onClick={() => goTo("connect")} className="flex shrink-0 items-center gap-2">
            <img src="/favicon.svg" alt="" className="size-6" />
            <span className="hidden text-[15px] font-semibold tracking-tight md:inline">Checkout Anything</span>
          </button>

          <nav className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5" aria-label="Screens">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => goTo(entry.id)}
                aria-current={tab === entry.id ? "page" : undefined}
                aria-label={entry.label}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors [&_svg]:size-3.5",
                  tab === entry.id ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {entry.icon}
                <span className={cn(tab !== entry.id && "hidden sm:inline")}>{entry.label}</span>
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            {USE_MOCK && (
              <Pill tone="warn" className="hidden sm:inline-flex">
                <FlaskConical className="size-3.5" /> Mock data, no backend
              </Pill>
            )}
            <Switch
              checked={mode === "replay"}
              onChange={(on) => setMode(on ? "replay" : "live")}
              label="Replay mode"
              compact
            />
            <ResetButton
              mode={mode}
              onError={setBanner}
              onDone={(firstStoreId) => {
                setBanner(null)
                setActiveStoreId(firstStoreId)
                refreshStores()
                bumpOrders()
                goTo("connect")
              }}
            />
            <AnimatedThemeToggler className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-4" />
          </div>
        </div>
        {mode === "replay" && (
          <div className="border-t border-border bg-warn-soft px-4 py-1.5 text-center text-xs text-warn">
            Replay mode: the page and Claude's answers come from recorded fixtures, labelled FIXTURE. PayPal sandbox
            calls still run live.
          </div>
        )}
        {(banner || missing.length > 0) && (
          <div role="alert" className="border-t border-border bg-bad-soft px-4 py-1.5 text-center text-xs text-bad">
            {banner || "The API is missing " + missing.join(", ") + ". Some steps will fail until they are set."}
          </div>
        )}
      </header>

      {/* all three screens stay mounted, so a run keeps streaming while you look at another tab */}
      <main className="flex-1">
        <div className={cn(tab !== "connect" && "hidden")}>
          <ConnectPage
            config={config}
            mode={mode}
            stores={stores}
            activeStoreId={activeStoreId}
            onPickStore={setActiveStoreId}
            onStoresChanged={refreshStores}
            onOrdersChanged={bumpOrders}
            onGoToAgent={() => goTo("agent")}
          />
        </div>
        <div className={cn(tab !== "agent" && "hidden")}>
          <AgentPage
            stores={stores}
            claudeReady={config ? config.claude_configured : true}
            onOrdersChanged={bumpOrders}
            onGoToConnect={() => goTo("connect")}
          />
        </div>
        <div className={cn(tab !== "orders" && "hidden")}>
          <OrdersPage active={tab === "orders"} refreshKey={ordersKey} onGoToAgent={goToAgent} />
        </div>
      </main>
    </div>
  )
}
