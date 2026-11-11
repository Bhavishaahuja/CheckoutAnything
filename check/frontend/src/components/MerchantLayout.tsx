import { FlaskConical } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { SESSION_EXPIRED_EVENT, USE_MOCKS, hasSession, logOut } from '../api'
import { CONNECT_URL } from '../lib/appLinks'
import { AppHeader, type HeaderLink, type Section } from './AppHeader'
import { LoginForm } from './LoginForm'
import { Pill } from '@/components/bits'
import { AnimatedThemeToggler } from '@/components/magicui/animated-theme-toggler'
import { useResetDemo } from '../lib/useResetDemo'
import { ResetButton, ResetStrip } from './ResetDemo'

type SessionState = 'in' | 'out' | 'expired'

// Shell for the merchant's screens. The human's confirm page skips this on purpose:
// on a phone they should see only the one decision in front of them.
//
// It's also the one login gate for every merchant page: no session token, no page. In mock
// mode hasSession() is always true, so a fresh clone still works with no setup.
export function MerchantLayout() {
  const [session, setSession] = useState<SessionState>(() => (hasSession() ? 'in' : 'out'))
  const reset = useResetDemo()

  useEffect(() => {
    // api.ts fires this on any 401 from a merchant route, from whichever page made the call
    function handleExpired() {
      setSession('expired')
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired)
  }, [])

  function handleLogOut() {
    logOut()
    setSession('out')
  }

  const loggedIn = session === 'in'

  // the shared header. Check and Disputes are pages of this app. Connect and Orders are screens of
  // the Checkout Anything app, which picks its screen from the hash
  const navigate = useNavigate()
  const location = useLocation()
  const headerLinks: Record<Section, HeaderLink> = {
    connect: { href: CONNECT_URL + '/#connect' },
    orders: { href: CONNECT_URL + '/#orders' },
    check: { href: '/dashboard', onNavigate: () => navigate('/dashboard') },
    disputes: { href: '/disputes', onNavigate: () => navigate('/disputes') },
  }
  // everything here that isn't Disputes is part of Check, the place-order page included
  const currentSection: Section = location.pathname.startsWith('/disputes') ? 'disputes' : 'check'

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <AppHeader
        current={currentSection}
        links={headerLinks}
        tools={
          <>
            <span className="ca-header__note">Fernwood Supply Co</span>
            {loggedIn && (
              <>
                <NavLink to="/place-order" className="ca-header__tool">
                  Place order
                </NavLink>
                <ResetButton controls={reset} />
              </>
            )}
            {loggedIn && !USE_MOCKS && (
              <button type="button" className="ca-header__tool" onClick={handleLogOut}>
                Log out
              </button>
            )}
            {USE_MOCKS && (
              <Pill tone="warn" className="hidden sm:inline-flex">
                <FlaskConical className="size-3.5" /> Sample data
              </Pill>
            )}
            {/* the same toggle as the Checkout Anything app, and the same saved "theme" key */}
            <AnimatedThemeToggler className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-4" />
          </>
        }
      >
        {loggedIn && <ResetStrip controls={reset} />}
      </AppHeader>
      <main className="mx-auto w-full max-w-[1400px] px-4 py-6">
        {loggedIn ? (
          <Outlet />
        ) : (
          <LoginForm expired={session === 'expired'} onLoggedIn={() => setSession('in')} />
        )}
      </main>
    </div>
  )
}
