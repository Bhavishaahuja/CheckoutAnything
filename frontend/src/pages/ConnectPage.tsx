import type { ColDef, GetRowIdParams, GridApi, RowClickedEvent } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { connectStore, eventsUrl, getSpec, getStores } from '../api'
import { CheckCell, MonoCell, StatusCell } from '../components/cells'
import SpecDrawer from '../components/SpecDrawer'
import { gridTheme } from '../gridTheme'
import { rowFromItem, rowsFromSpec } from '../rows'
import type { AppConfig, CatalogRow, Mode, RunEvent, SpecItem, Store, StoreSpec } from '../types'

// every event type the API streams. EventSource needs a listener per named event
const EVENT_TYPES = [
  'fetch.started', 'fetch.done', 'extract.started', 'extract.done', 'item.checking',
  'item.verified', 'item.failed', 'item.repairing', 'store.ready', 'error',
]

// how long a row keeps its flash class. matches the row-flash animation in index.css
const FLASH_MS = 1800

function iconFor(event: RunEvent): { icon: string; tone: string } {
  if (event.type === 'error') return { icon: '✗', tone: 'bad' }
  if (event.type === 'item.failed') return { icon: '✗', tone: 'bad' }
  if (event.type === 'item.verified') return { icon: '✓', tone: 'good' }
  if (event.type === 'store.ready') {
    return event.data.status === 'live' ? { icon: '✓', tone: 'good' } : { icon: '✗', tone: 'bad' }
  }
  if (event.type.endsWith('.done')) return { icon: '✓', tone: 'good' }
  return { icon: '⟳', tone: 'busy' }
}

const COLUMNS: ColDef<CatalogRow>[] = [
  { field: 'name', headerName: 'Item', flex: 2, minWidth: 140 },
  {
    headerName: 'Options',
    width: 100,
    valueGetter: (params) => {
      const row = params.data
      if (!row) return ''
      const parts: string[] = []
      if (row.variantCount > 0) parts.push(row.variantCount + (row.variantCount === 1 ? ' variant' : ' variants'))
      if (row.addOnCount > 0) parts.push(row.addOnCount + (row.addOnCount === 1 ? ' add-on' : ' add-ons'))
      return parts.join(', ')
    },
  },
  {
    field: 'price',
    headerName: 'Price',
    width: 96,
    type: 'rightAligned',
    // a number for sorting, the exact string for display
    comparator: (a: string, b: string) => Number(a) - Number(b),
    valueFormatter: (params) => (params.data ? params.value + ' ' + params.data.currency : ''),
    cellClass: 'mono',
    enableCellChangeFlash: true,
  },
  { field: 'pageCheck', headerName: 'Page check', width: 118, cellRenderer: CheckCell },
  { field: 'paypalCheck', headerName: 'PayPal check', width: 130, cellRenderer: CheckCell },
  { field: 'repairs', headerName: 'Repairs', width: 92, type: 'rightAligned' },
  { field: 'paypalOrderId', headerName: 'PayPal order id', flex: 1, minWidth: 140, cellRenderer: MonoCell },
  { field: 'status', headerName: 'Status', width: 125, cellRenderer: StatusCell },
]

const DEFAULT_COLUMN: ColDef = { sortable: true, resizable: true, suppressMovable: true }

interface Props {
  mode: Mode
  config: AppConfig | null
}

export default function ConnectPage({ mode, config }: Props) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [stores, setStores] = useState<Store[]>([])
  const [storeId, setStoreId] = useState<number | null>(null)
  const [log, setLog] = useState<RunEvent[]>([])
  const [spec, setSpec] = useState<StoreSpec | null>(null)
  const [openItem, setOpenItem] = useState<string | null>(null)
  // goes up whenever the run moves on, the open drawer reloads on it
  const [progress, setProgress] = useState(0)

  const gridApi = useRef<GridApi<CatalogRow> | null>(null)
  // the rows as we know them. the grid is fed from here through transactions
  const rows = useRef<Map<string, CatalogRow>>(new Map())
  const source = useRef<EventSource | null>(null)
  const flashTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const logEnd = useRef<HTMLDivElement | null>(null)

  const refreshStores = useCallback(() => {
    getStores()
      .then(setStores)
      .catch(() => {
        // the banner at the top already says when the API can't be reached
      })
  }, [])

  // ---- rows ----

  const replaceRows = useCallback((next: CatalogRow[]) => {
    rows.current = new Map(next.map((row) => [row.id, row]))
    gridApi.current?.setGridOption('rowData', next)
  }, [])

  // change one row with a transaction, so only that row redraws
  const patchRow = useCallback((id: string, change: Partial<CatalogRow>) => {
    const current = rows.current.get(id)
    if (!current) return
    const next = { ...current, ...change }
    rows.current.set(id, next)
    gridApi.current?.applyTransaction({ update: [next] })
  }, [])

  const flashRow = useCallback(
    (id: string, flash: 'ok' | 'fail') => {
      patchRow(id, { flash })
      const waiting = flashTimers.current.get(id)
      if (waiting) clearTimeout(waiting)
      flashTimers.current.set(
        id,
        setTimeout(() => patchRow(id, { flash: null }), FLASH_MS),
      )
    },
    [patchRow],
  )

  const applyItem = useCallback(
    (item: SpecItem | undefined) => {
      // a repair can change the name, price and options
      if (!item) return
      patchRow(item.id, {
        name: item.name,
        price: item.unit_price,
        variantCount: item.variants.length,
        addOnCount: item.add_ons.length,
      })
    },
    [patchRow],
  )

  // ---- events ----

  const closeStream = useCallback(() => {
    source.current?.close()
    source.current = null
  }, [])

  const onEvent = useCallback(
    (event: RunEvent) => {
      setLog((before) => {
        // a reconnect can replay events we already have
        if (before.some((one) => one.seq === event.seq)) return before
        return [...before, event]
      })

      const id = event.item_id
      const data = event.data

      if (event.type === 'extract.done') {
        const loaded = data.spec as StoreSpec
        setSpec(loaded)
        replaceRows(loaded.items.map((item) => rowFromItem(item, loaded.merchant.currency)))
      } else if (event.type === 'item.checking' && id) {
        applyItem(data.item)
        patchRow(id, { status: 'checking', pageCheck: 'pending', paypalCheck: 'pending', reason: null })
      } else if (event.type === 'item.verified' && id) {
        applyItem(data.item)
        patchRow(id, {
          status: 'verified',
          pageCheck: 'ok',
          paypalCheck: 'ok',
          paypalOrderId: data.paypal_order_id,
          reason: null,
        })
        flashRow(id, 'ok')
      } else if (event.type === 'item.failed' && id) {
        const change: Partial<CatalogRow> = { reason: data.reason ?? null }
        if (data.page_check_ok !== undefined) {
          change.pageCheck = data.page_check_ok ? 'ok' : 'fail'
          if (data.paypal_check_ok === null) change.paypalCheck = 'skipped'
          else change.paypalCheck = data.paypal_check_ok ? 'ok' : 'fail'
        }
        if (data.paypal_order_id) change.paypalOrderId = data.paypal_order_id
        if (data.unavailable) change.status = 'unavailable'
        else change.status = 'failed'
        patchRow(id, change)
        flashRow(id, 'fail')
      } else if (event.type === 'item.repairing' && id) {
        patchRow(id, { status: 'repairing', repairs: data.attempt })
      } else if (event.type === 'store.ready' || event.type === 'error') {
        if (data.spec) setSpec(data.spec as StoreSpec)
        closeStream()
        refreshStores()
      }
      setProgress((count) => count + 1)
    },
    [applyItem, closeStream, flashRow, patchRow, refreshStores, replaceRows],
  )

  const openStream = useCallback(
    (id: number) => {
      closeStream()
      const stream = new EventSource(eventsUrl(id))
      source.current = stream
      const handle = (message: MessageEvent) => onEvent(JSON.parse(message.data) as RunEvent)
      for (const type of EVENT_TYPES) {
        // "error" is also what EventSource calls a dropped connection, which has no data
        stream.addEventListener(type, (message) => {
          if ((message as MessageEvent).data) handle(message as MessageEvent)
        })
      }
      stream.onerror = () => {
        // a finished run with no live log left answers 410. don't keep retrying that
        if (stream.readyState === EventSource.CLOSED || source.current !== stream) return
        stream.close()
        if (source.current === stream) source.current = null
      }
    },
    [closeStream, onEvent],
  )

  // ---- picking a store ----

  const showStore = useCallback(
    async (id: number) => {
      closeStream()
      setStoreId(id)
      setLog([])
      setSpec(null)
      setOpenItem(null)
      replaceRows([])
      try {
        // what the database has, in case the live log is gone
        const loaded = await getSpec(id)
        if (loaded.spec) {
          setSpec(loaded.spec)
          replaceRows(rowsFromSpec(loaded.spec, loaded.runs))
        }
      } catch {
        // a store that failed before it had a spec. the log below will say why
      }
      // then the log, which replays the run from the start if the API still has it
      openStream(id)
    },
    [closeStream, openStream, replaceRows],
  )

  useEffect(() => {
    // first load: show the newest store, if there is one
    let cancelled = false
    getStores()
      .then((loaded) => {
        if (cancelled) return
        setStores(loaded)
        if (loaded.length > 0) void showStore(loaded[loaded.length - 1].id)
      })
      .catch(() => {})
    const timers = flashTimers.current
    return () => {
      cancelled = true
      closeStream()
      for (const timer of timers.values()) clearTimeout(timer)
    }
    // once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // keep the store chips fresh while anything is still connecting
  const anyConnecting = stores.some((store) => store.status === 'connecting')
  useEffect(() => {
    if (!anyConnecting) return
    const timer = setInterval(refreshStores, 2000)
    return () => clearInterval(timer)
  }, [anyConnecting, refreshStores])

  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: 'nearest' })
  }, [log.length])

  const onSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      const trimmed = url.trim()
      if (!trimmed) return
      setBusy(true)
      setFormError(null)
      try {
        const started = await connectStore(trimmed, mode)
        refreshStores()
        await showStore(started.store_id)
      } catch (error) {
        setFormError((error as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [mode, refreshStores, showStore, url],
  )

  const getRowId = useCallback((params: GetRowIdParams<CatalogRow>) => params.data.id, [])
  const onRowClicked = useCallback((event: RowClickedEvent<CatalogRow>) => {
    if (event.data) setOpenItem(event.data.id)
  }, [])
  const rowClassRules = useMemo(
    () => ({
      'row--flash-ok': (params: { data?: CatalogRow }) => params.data?.flash === 'ok',
      'row--flash-fail': (params: { data?: CatalogRow }) => params.data?.flash === 'fail',
      'row--unavailable': (params: { data?: CatalogRow }) => params.data?.status === 'unavailable',
    }),
    [],
  )

  const current = stores.find((store) => store.id === storeId) ?? null
  const fromFixture = log.some((event) => event.data.fixture === true) || current?.mode === 'replay'
  const demoUrls = config?.demo_store_urls ?? []

  return (
    <div className="connect">
      <section className="hero">
        <h1>Make any store agent-ready from just a URL</h1>
        <p className="hero__sub">
          Paste a store page. Claude reads it and writes a store spec, then fixed code checks
          every item against the page and against PayPal with a real sandbox order.
        </p>
        <form className="urlform" onSubmit={onSubmit}>
          <input
            className="input"
            type="url"
            inputMode="url"
            placeholder="https://your-store.example/menu"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            aria-label="Store URL"
            required
          />
          <button className="button button--primary" type="submit" disabled={busy}>
            {busy ? 'Starting...' : 'Make it agent-ready'}
          </button>
        </form>
        {demoUrls.length > 0 && (
          <div className="tryrow">
            <span className="faint">Try a demo store:</span>
            {demoUrls.map((demoUrl) => (
              <button key={demoUrl} className="linkbutton" onClick={() => setUrl(demoUrl)}>
                {demoUrl.replace(/\/$/, '').split('/').pop()}
              </button>
            ))}
          </div>
        )}
        {formError && <div className="banner banner--bad banner--inline">{formError}</div>}
      </section>

      {stores.length > 0 && (
        <div className="storechips" role="tablist" aria-label="Connected stores">
          {stores.map((store) => (
            <button
              key={store.id}
              role="tab"
              aria-selected={store.id === storeId}
              className={'storechip' + (store.id === storeId ? ' storechip--active' : '')}
              onClick={() => void showStore(store.id)}
              title={store.source_url}
            >
              <span className={'dot dot--' + store.status} aria-hidden="true" />
              {store.merchant_name || 'Store ' + store.id}
              <span className="storechip__count">
                {store.status === 'connecting' ? 'connecting' : store.counts.verified + ' verified'}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="workspace">
        <section className="panel panel--log" aria-label="Live steps">
          <div className="panel__head">
            <h2>Live steps</h2>
            {fromFixture && <span className="fixture">FIXTURE</span>}
          </div>
          <div className="log">
            {log.length === 0 && (
              <p className="faint log__empty">
                {storeId === null
                  ? 'Each step of the connect run shows up here as it happens.'
                  : 'No live log for this store. The grid shows what was saved.'}
              </p>
            )}
            {log.map((event) => {
              const { icon, tone } = iconFor(event)
              return (
                <div key={event.seq} className={'logline logline--' + tone}>
                  <span className="logline__icon" aria-hidden="true">{icon}</span>
                  <span>{event.message}</span>
                </div>
              )
            })}
            <div ref={logEnd} />
          </div>
        </section>

        <section className="panel panel--grid" aria-label="Catalog">
          <div className="panel__head">
            <h2>{spec ? spec.merchant.name : 'Catalog'}</h2>
            {spec && (
              <span className="faint">
                {spec.shipping.type === 'flat'
                  ? 'Flat shipping ' + spec.shipping.amount + ' ' + spec.merchant.currency
                  : 'No shipping fee'}
                {' · click a row for its spec'}
              </span>
            )}
          </div>
          <div className="grid-wrap">
            <AgGridReact<CatalogRow>
              theme={gridTheme}
              columnDefs={COLUMNS}
              defaultColDef={DEFAULT_COLUMN}
              // no rowData prop: the rows only ever go in through the grid api (see replaceRows
              // and patchRow), a prop here would overwrite them on every render
              getRowId={getRowId}
              rowClassRules={rowClassRules}
              onRowClicked={onRowClicked}
              onGridReady={(event) => {
                gridApi.current = event.api
                event.api.setGridOption('rowData', Array.from(rows.current.values()))
              }}
              animateRows
              suppressCellFocus
              overlayNoRowsTemplate="Paste a store URL above. The catalog fills in here, one verified row at a time."
            />
          </div>
          {spec && spec.extraction_notes.length > 0 && (
            <div className="notesbox">
              <h3>Claude's extraction notes</h3>
              <ul className="notes">
                {spec.extraction_notes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>

      {storeId !== null && openItem && (
        <SpecDrawer
          storeId={storeId}
          itemId={openItem}
          refreshKey={progress}
          onClose={() => setOpenItem(null)}
        />
      )}
    </div>
  )
}
