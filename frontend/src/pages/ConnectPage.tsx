// Screen 1: paste a URL, watch the store become agent-ready.

import { ArrowRight, ExternalLink, Link2, Store as StoreIcon } from "lucide-react"
import { AnimatePresence } from "motion/react"
import { useCallback, useMemo, useState, type FormEvent } from "react"

import { Card, ErrorNote, Pill, StoreStatusPill } from "@/components/bits"
import { CatalogGrid } from "@/components/CatalogGrid"
import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text"
import { AuroraText } from "@/components/magicui/aurora-text"
import { BlurFade } from "@/components/magicui/blur-fade"
import { BorderBeam } from "@/components/magicui/border-beam"
import { DotPattern } from "@/components/magicui/dot-pattern"
import { NumberTicker } from "@/components/magicui/number-ticker"
import { ShimmerButton } from "@/components/magicui/shimmer-button"
import { PipelineBeam } from "@/components/PipelineBeam"
import { SpecDrawer } from "@/components/SpecDrawer"
import { StepLog } from "@/components/StepLog"
import { api } from "@/lib/api"
import { hostAndPath } from "@/lib/format"
import { useRun } from "@/lib/run"
import type { AppConfig, Mode, Store } from "@/lib/types"
import { cn } from "@/lib/utils"

function prettyName(url: string) {
  // "https://x/hollowbrook-bakery/" -> "Hollowbrook Bakery"
  const parts = url.replace(/\/$/, "").split("/")
  const slug = parts[parts.length - 1] || url
  return slug
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}

function Counter({ value, label, tone }: { value: number; label: string; tone: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={cn("text-xl font-semibold tabular-nums", tone)}>
        {value === 0 ? "0" : <NumberTicker value={value} className={tone} />}
      </span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

export function ConnectPage({
  config,
  mode,
  stores,
  activeStoreId,
  onPickStore,
  onStoresChanged,
  onOrdersChanged,
  onGoToAgent,
}: {
  config: AppConfig | null
  mode: Mode
  stores: Store[]
  activeStoreId: number | null
  onPickStore: (storeId: number | null) => void
  onStoresChanged: () => void
  onOrdersChanged: () => void
  onGoToAgent: () => void
}) {
  const [url, setUrl] = useState("")
  const [starting, setStarting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formNote, setFormNote] = useState<string | null>(null)
  const [openItemId, setOpenItemId] = useState<string | null>(null)

  const run = useRun(activeStoreId, onStoresChanged)
  // every saved change in the grid (a publish above all) also refetches the store list, so the
  // "N of M live" chips here and in the Agent sidebar never lag behind what an agent can buy
  const runReload = run.reload
  const reloadWithStores = useCallback(async () => {
    await runReload()
    onStoresChanged()
  }, [runReload, onStoresChanged])
  const connecting = run.status === "connecting"
  const repairing = run.rows.some((row) => row.status === "repairing")
  const openRow = openItemId ? run.rows.find((row) => row.item_id === openItemId) || null : null
  const hasRun = activeStoreId !== null

  const connect = async (target: string) => {
    const cleaned = target.trim()
    if (!cleaned) {
      setFormError("Paste a store URL first")
      return
    }
    setStarting(true)
    setFormError(null)
    setFormNote(null)
    setOpenItemId(null)
    try {
      const started = await api.connectStore(cleaned, mode)
      if (started.already_connected) setFormNote(started.message || "This store is already connected")
      onPickStore(started.store_id)
      onStoresChanged()
    } catch (problem) {
      setFormError(problem instanceof Error ? problem.message : "Couldn't start connecting")
    } finally {
      setStarting(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void connect(url)
  }

  // what the grid's loading overlay says before the first item shows up
  const lastEvent = run.events.length > 0 ? run.events[run.events.length - 1].type : null
  const loadingStep = useMemo(() => {
    if (lastEvent === "fetch.started") return { label: "Step 1 of 3: fetching the page", progress: 0.15 }
    if (lastEvent === "fetch.done") return { label: "Step 1 of 3: the page is in", progress: 0.35 }
    if (lastEvent === "extract.started") return { label: "Step 2 of 3: Claude is writing the store spec", progress: 0.6 }
    if (lastEvent === "extract.done") return { label: "Step 3 of 3: checking each item against the page and PayPal", progress: 0.9 }
    return { label: "Starting the run", progress: 0.05 }
  }, [lastEvent])

  const firstDemoUrl = config && config.demo_store_urls.length > 0 ? config.demo_store_urls[0] : null
  const connectDemo = () => {
    if (!firstDemoUrl) return
    setUrl(firstDemoUrl)
    void connect(firstDemoUrl)
  }

  const liveCount = run.review ? run.rows.filter((row) => row.published).length : run.counts.verified

  const activeStore = stores.find((store) => store.id === activeStoreId) || null
  const sourceUrl = run.detail?.store.source_url || activeStore?.source_url || ""
  const isFixture = (run.detail?.store.mode || activeStore?.mode) === "replay"

  return (
    <div className="relative">
      {/* hero */}
      <section className={cn("relative overflow-hidden border-b border-border", hasRun ? "py-6" : "py-12 sm:py-16")}>
        <DotPattern
          width={22}
          height={22}
          cr={1}
          className="text-muted-foreground/25 [mask-image:radial-gradient(520px_circle_at_center,white,transparent)]"
        />
        <div className="relative mx-auto flex max-w-3xl flex-col items-center px-4 text-center">
          {!hasRun && (
            <BlurFade delay={0.05}>
              <div className="mb-5 inline-flex rounded-full border border-border bg-card/80 px-3.5 py-1 text-[13px]">
                <AnimatedShinyText>PayPal sandbox + Claude. No integration needed on the store.</AnimatedShinyText>
              </div>
              <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
                Make <AuroraText colors={["#1d3fd0", "#12805c", "#3b82f6", "#0ea5a4"]}>any store</AuroraText>{" "}
                agent-ready, from just a URL
              </h1>
              <p className="mx-auto mt-4 max-w-xl text-base text-pretty text-muted-foreground">
                Claude reads the page and writes a store spec. Fixed code checks every price against the page and a
                real PayPal sandbox order. Then any AI shopping agent can buy from it.
              </p>
            </BlurFade>
          )}

          <form onSubmit={onSubmit} className={cn("w-full", !hasRun && "mt-8")}>
            <div className="relative flex flex-col gap-2 rounded-2xl border border-border bg-card p-2 shadow-sm sm:flex-row sm:items-center">
              <label className="flex min-w-0 flex-1 items-center gap-2.5 px-3">
                <Link2 className="size-4 shrink-0 text-muted-foreground" />
                <span className="sr-only">Store URL</span>
                <input
                  type="url"
                  inputMode="url"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://your-store.example/shop"
                  className="h-11 w-full min-w-0 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground/70"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <ShimmerButton
                type="submit"
                disabled={starting || connecting}
                background="var(--primary)"
                shimmerColor="#ffffff"
                borderRadius="12px"
                className="h-11 shrink-0 px-5 text-sm font-medium text-primary-foreground disabled:opacity-60 dark:text-primary-foreground"
              >
                <span className="flex items-center gap-2">
                  {connecting ? "Connecting" : "Make it agent-ready"} <ArrowRight className="size-4" />
                </span>
              </ShimmerButton>
              {connecting && <BorderBeam size={90} duration={5} colorFrom="var(--primary)" colorTo="var(--ok)" />}
            </div>
          </form>

          {formError && (
            <div className="mt-3 w-full text-left">
              <ErrorNote>{formError}</ErrorNote>
            </div>
          )}
          {formNote && !formError && (
            <p className="mt-3 w-full text-left text-sm text-muted-foreground" role="status">
              {formNote}
            </p>
          )}

          {config && config.demo_store_urls.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-[13px]">
              <span className="text-muted-foreground">Try a demo store:</span>
              {config.demo_store_urls.map((demoUrl) => (
                <button
                  key={demoUrl}
                  type="button"
                  disabled={starting || connecting}
                  onClick={() => {
                    setUrl(demoUrl)
                    void connect(demoUrl)
                  }}
                  className="h-8 rounded-full border border-border bg-card px-3 transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
                >
                  {prettyName(demoUrl)}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6">
        {/* the path a store takes */}
        <Card className="px-4 py-5 sm:px-10">
          <PipelineBeam stage={run.stage} repairing={repairing} />
        </Card>

        {/* stores connected so far */}
        {stores.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Stores</span>
            {stores.map((store) => (
              <button
                key={store.id}
                type="button"
                onClick={() => {
                  setOpenItemId(null)
                  onPickStore(store.id)
                }}
                className={cn(
                  "flex h-9 items-center gap-2 rounded-lg border px-3 text-[13px] transition-colors",
                  store.id === activeStoreId ? "border-primary bg-info-soft" : "border-border bg-card hover:bg-muted"
                )}
              >
                <span
                  className={cn(
                    "size-2 rounded-full",
                    store.status === "live" && "bg-ok",
                    store.status === "failed" && "bg-bad",
                    store.status === "connecting" && "animate-pulse bg-primary"
                  )}
                />
                <span className="font-medium">{store.merchant_name || prettyName(store.source_url)}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {store.status === "connecting" ? "connecting" : store.counts.verified + " verified"}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* log + catalog */}
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <Card className="flex h-[300px] flex-col overflow-hidden lg:h-[640px]">
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
              <h2 className="text-sm font-semibold">Live steps</h2>
              {run.events.length > 0 && <span className="text-xs text-muted-foreground tabular-nums">{run.events.length} events</span>}
            </div>
            <div className="min-h-0 flex-1">
              <StepLog events={run.events} running={connecting} selectedItemId={openItemId} onPickItem={setOpenItemId} />
            </div>
          </Card>

          <Card className="flex h-[640px] flex-col overflow-hidden">
            <div className="flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-2">
              <div className="flex min-w-0 items-center gap-2.5">
                <StoreIcon className="size-4 shrink-0 text-muted-foreground" />
                <h2 className="truncate text-sm font-semibold">{run.merchantName || (connecting ? "Reading the store" : sourceUrl ? prettyName(sourceUrl) : "Catalog")}</h2>
                <StoreStatusPill status={run.status} />
                {isFixture && (
                  <Pill tone="warn" className="font-mono tracking-wider">
                    FIXTURE
                  </Pill>
                )}
                {sourceUrl && (
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="hidden min-w-0 items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground md:flex"
                  >
                    <span className="truncate">{hostAndPath(sourceUrl)}</span>
                    <ExternalLink className="size-3 shrink-0" />
                  </a>
                )}
              </div>
              <div className="flex items-center gap-5">
                <Counter value={run.counts.verified} label="verified" tone="text-ok" />
                <Counter value={run.counts.failed} label="failed" tone="text-bad" />
                <Counter value={run.counts.unavailable} label="not for sale" tone="text-muted-foreground" />
              </div>
            </div>

            {run.error && run.rows.length > 0 && (
              <div className="px-4 pt-3">
                <ErrorNote>{run.error}</ErrorNote>
              </div>
            )}

            <div className="min-h-0 flex-1">
              <CatalogGrid
                storeId={activeStoreId}
                rows={run.rows}
                review={run.review}
                merchantName={run.merchantName || (sourceUrl ? prettyName(sourceUrl) : "")}
                status={run.status}
                loadingStep={loadingStep}
                storeError={run.error}
                selectedItemId={openItemId}
                onPickItem={setOpenItemId}
                reload={reloadWithStores}
                onConnectDemo={firstDemoUrl && !starting ? connectDemo : undefined}
              />
            </div>

            {run.status === "live" && (
              <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border bg-ok-soft/50 px-4 py-2.5 text-[13px]">
                <span>
                  <span className="font-medium">{run.merchantName} is live.</span>{" "}
                  <span className="text-muted-foreground">
                    {liveCount === run.counts.verified
                      ? "A shopping agent can buy its " + liveCount + " verified " + (liveCount === 1 ? "item" : "items") + " through PayPal right now."
                      : liveCount + " of its " + run.counts.verified + " verified " + (run.counts.verified === 1 ? "item" : "items") + " " + (liveCount === 1 ? "is" : "are") + " live on PayPal. " + (run.counts.verified - liveCount === 1 ? "The other one waits" : "The rest wait") + " for you to confirm the amber cells and publish."}
                  </span>
                </span>
                <button type="button" onClick={onGoToAgent} className="flex items-center gap-1 font-medium text-primary hover:underline">
                  Send an agent shopping <ArrowRight className="size-3.5" />
                </button>
              </div>
            )}
            {connecting && <BorderBeam size={140} duration={7} colorFrom="var(--primary)" colorTo="var(--ok)" />}
          </Card>
        </div>
      </div>

      <AnimatePresence>
        {openRow && activeStoreId !== null && (
          <SpecDrawer
            key="drawer"
            row={openRow}
            detail={run.detail}
            storeId={activeStoreId}
            onClose={() => setOpenItemId(null)}
            onBought={onOrdersChanged}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
