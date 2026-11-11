// Merchant password login. Moved here from PlaceOrderPage so MerchantLayout can put it in front
// of every merchant page. The password goes to POST /auth/session and is never kept, only the
// session token is (see api.ts).

import { useState, type FormEvent } from 'react'
import { LockKeyhole } from 'lucide-react'
import { logIn } from '../api'
import { Card, ErrorNote } from '@/components/bits'
import { Button } from '@/components/ui/button'

interface LoginFormProps {
  onLoggedIn: () => void
  // set when we got here because a session ran out, not on a first visit
  expired?: boolean
}

export function LoginForm({ onLoggedIn, expired = false }: LoginFormProps) {
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await logIn(password)
      onLoggedIn()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Login failed')
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4 py-10">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="flex size-11 items-center justify-center rounded-full bg-info-soft text-primary">
          <LockKeyhole className="size-5" aria-hidden />
        </span>
        <h1 className="text-xl font-semibold tracking-tight">Log in</h1>
        <p className="text-sm text-pretty text-muted-foreground">
          {expired
            ? 'Your session ran out. Log in again to keep going.'
            : 'Merchant staff only. Agent orders and review links live behind this.'}
        </p>
      </div>
      <Card className="p-4">
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <label className="text-[13px] font-medium" htmlFor="demo-password">
            Merchant password
          </label>
          <input
            id="demo-password"
            className="h-10 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary"
            type="password"
            autoComplete="current-password"
            required
            autoFocus
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" size="lg" disabled={submitting}>
            {submitting ? 'Logging in...' : 'Log in'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
