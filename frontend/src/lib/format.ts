export function money(amount: string | number, currency = "USD") {
  const value = typeof amount === "string" ? Number(amount) : amount
  if (Number.isNaN(value)) return String(amount)
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value)
}

export function clockTime(iso: string | null) {
  if (!iso) return ""
  const date = new Date(iso)
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })
}

// how long a human took to decide: "0.7s", "42s", "3m 5s"
export function decisionTime(ms: number | null) {
  if (ms === null || ms === undefined) return ""
  if (ms < 10000) return (ms / 1000).toFixed(1) + "s"
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return seconds + "s"
  return Math.floor(seconds / 60) + "m " + (seconds % 60) + "s"
}

export function dateAndTime(iso: string | null) {
  if (!iso) return ""
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}

export function hostAndPath(url: string) {
  try {
    const parsed = new URL(url)
    return parsed.host + parsed.pathname.replace(/\/$/, "")
  } catch {
    return url
  }
}
