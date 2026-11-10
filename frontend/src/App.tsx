import { Bot, FlaskConical, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { AppHeader, type HeaderLink, type Section } from "@/components/AppHeader"
import { Pill, Switch } from "@/components/bits"
import { AnimatedThemeToggler } from "@/components/magicui/animated-theme-toggler"
import { Button } from "@/components/ui/button"
import { api, USE_MOCK } from "@/lib/api"
import { CHECK_URL } from "@/lib/appLinks"
import type { AppConfig, Mode, Store } from "@/lib/types"
import { cn } from "@/lib/utils"
import { AgentPage } from "@/pages/AgentPage"
import { ConnectPage } from "@/pages/ConnectPage"
import { DisputesPage } from "@/pages/DisputesPage"
import { OrdersPage } from "@/pages/OrdersPage"

type Tab = "connect" | "agent" | "orders" | "disputes"

const TABS: Tab[] = ["connect", "agent", "orders", "disputes"]

function tabFromHash(): Tab {
  const wanted = window.location.hash.replace("#", "")
  for (const tab of TABS) {
    if (tab === wanted) return tab
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

  const checkOn = config ? config.check_configured : false
  const disputesOn = config ? config.check_merchant_configured : false

  // the shared header. Connect and Orders are screens of this app. Check is the other app. Disputes
  // is a screen here when the API can reach Check, and the Check app's own page when it can't
  const headerLinks: Record<Section, HeaderLink> = {
    connect: { href: "#connect", onNavigate: () => goTo("connect") },
    orders: { href: "#orders", onNavigate: () => goTo("orders") },
    check: { href: CHECK_URL + "/dashboard" },
    disputes: disputesOn
      ? { href: "#disputes", onNavigate: () => goTo("disputes") }
      : { href: CHECK_URL + "/disputes" },
  }
  // the agent screen is none of the four, so nothing is highlighted there but its own button
  const currentSection: Section | null = tab === "agent" ? null : tab

  const missing: string[] = []
  if (config && !config.paypal_configured) missing.push("PayPal sandbox keys")
  if (config && !config.claude_configured) missing.push("the Claude API key")
  if (config && !config.vault_configured) missing.push("the saved buyer (vault id)")

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader
        current={currentSection}
        links={headerLinks}
        tools={
          <>
            {/* the demo shopping agent is this app's own screen, not one of the four shared sections */}
            <a
              href="#agent"
              className="ca-header__tool gap-1.5 [&_svg]:size-3.5"
              aria-current={tab === "agent" ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault()
                goTo("agent")
              }}
            >
              <Bot /> Agent
            </a>
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
          </>
        }
      >
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
      </AppHeader>

      {/* every screen stays mounted, so a run keeps streaming while you look at another tab */}
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
          <OrdersPage
            active={tab === "orders"}
            refreshKey={ordersKey}
            checkOn={checkOn}
            reviewLinks={config ? config.check_review_links : false}
            onGoToAgent={goToAgent}
          />
        </div>
        {disputesOn && (
          <div className={cn(tab !== "disputes" && "hidden")}>
            <DisputesPage active={tab === "disputes"} />
          </div>
        )}
      </main>
    </div>
  )
}
