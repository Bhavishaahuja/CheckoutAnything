import { useCallback, useEffect, useState } from 'react'
import { getConfig, resetDemo } from './api'
import AgentPage from './pages/AgentPage'
import ConnectPage from './pages/ConnectPage'
import OrdersPage from './pages/OrdersPage'
import type { AppConfig, Mode } from './types'

type Tab = 'connect' | 'agent' | 'orders'

const TABS: { id: Tab; label: string }[] = [
  { id: 'connect', label: 'Connect' },
  { id: 'agent', label: 'Agent' },
  { id: 'orders', label: 'Orders' },
]

function savedMode(): Mode | null {
  const saved = window.localStorage.getItem('mode')
  return saved === 'live' || saved === 'replay' ? saved : null
}

export default function App() {
  const [tab, setTab] = useState<Tab>('connect')
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>(savedMode() ?? 'live')
  const [resetting, setResetting] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  // bumps after a reset, so the pages throw away what they were showing
  const [resetCount, setResetCount] = useState(0)

  useEffect(() => {
    getConfig()
      .then((loaded) => {
        setConfig(loaded)
        // the API's default only applies until someone flips the toggle
        if (savedMode() === null) setMode(loaded.default_mode)
      })
      .catch((error: Error) => setConfigError(error.message))
  }, [])

  const chooseMode = useCallback((next: Mode) => {
    setMode(next)
    window.localStorage.setItem('mode', next)
  }, [])

  const onReset = useCallback(async () => {
    const sure = window.confirm(
      'Reset the demo? This forgets every store and order here and reconnects the three demo stores.',
    )
    if (!sure) return
    setResetting(true)
    setResetError(null)
    try {
      await resetDemo(mode)
      setResetCount((count) => count + 1)
      setTab('connect')
    } catch (error) {
      setResetError((error as Error).message)
    } finally {
      setResetting(false)
    }
  }, [mode])

  const missing: string[] = []
  if (config && !config.paypal_configured) missing.push('PayPal sandbox keys')
  if (config && !config.claude_configured) missing.push('the Anthropic key (live mode and the agent need it)')
  if (config && !config.vault_configured) missing.push('BUYER_VAULT_ID (buying needs it)')

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__inner">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true">✓</span>
            <span className="brand__name">Checkout Anything</span>
          </div>
          <nav className="tabs" aria-label="Sections">
            {TABS.map((one) => (
              <button
                key={one.id}
                className={'tab' + (tab === one.id ? ' tab--active' : '')}
                onClick={() => setTab(one.id)}
              >
                {one.label}
              </button>
            ))}
          </nav>
          <div className="topbar__right">
            <label className="toggle" title="Replay recorded runs instead of fetching pages and calling Claude. PayPal sandbox calls still run live.">
              <input
                type="checkbox"
                checked={mode === 'replay'}
                onChange={(event) => chooseMode(event.target.checked ? 'replay' : 'live')}
              />
              <span>Replay mode</span>
            </label>
            <button className="button button--quiet" onClick={onReset} disabled={resetting}>
              {resetting ? 'Resetting...' : 'Reset demo'}
            </button>
          </div>
        </div>
      </header>

      {configError && <div className="banner banner--bad">{configError}</div>}
      {resetError && <div className="banner banner--bad">Reset failed: {resetError}</div>}
      {missing.length > 0 && (
        <div className="banner banner--warn">Not set on the API: {missing.join(', ')}.</div>
      )}
      {mode === 'replay' && (
        <div className="banner banner--info">
          Replay mode: store pages and Claude's answers come from recorded fixtures (labelled
          FIXTURE). Every PayPal sandbox order is still created live.
        </div>
      )}

      <main className="main">
        {/* all three stay mounted, so a connect run keeps streaming while you look at orders */}
        <div hidden={tab !== 'connect'}>
          <ConnectPage key={'connect-' + resetCount} mode={mode} config={config} />
        </div>
        <div hidden={tab !== 'agent'}>
          <AgentPage key={'agent-' + resetCount} />
        </div>
        <div hidden={tab !== 'orders'}>
          <OrdersPage key={'orders-' + resetCount} visible={tab === 'orders'} />
        </div>
      </main>

      <footer className="footer">
        Sandbox only. The stores are fictional. Claude writes the spec as JSON, fixed code makes
        every PayPal call.
      </footer>
    </div>
  )
}
