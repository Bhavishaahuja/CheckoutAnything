import { useEffect, useState } from 'react'

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: Error }
  | { status: 'ready'; data: T }

// Runs a loader once per `load` identity. Callers wrap the loader in useCallback,
// or key the component, so it doesn't refetch on every render.
export function useAsync<T>(load: () => Promise<T>): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' })

  useEffect(() => {
    // ignore results that land after the component moved on
    let cancelled = false
    load().then(
      (data) => {
        if (!cancelled) {
          setState({ status: 'ready', data })
        }
      },
      (error: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', error: error instanceof Error ? error : new Error(String(error)) })
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [load])

  return state
}
