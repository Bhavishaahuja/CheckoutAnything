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

// "Nov 10, 2:14 PM", for a date column
export function shortDateTime(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}

// "2026-11-10" in local time, for file names
export function dayStamp(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0")
  return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
}

// "Fernwood & Thistle Goods" -> "fernwood-thistle-goods"
export function slugify(text: string) {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "store"
  )
}

// "1.4s", "12s", "3m 05s": how long a person took
export function duration(ms: number) {
  if (ms < 10_000) return (ms / 1000).toFixed(1) + "s"
  if (ms < 60_000) return Math.round(ms / 1000) + "s"
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return minutes + "m " + String(seconds).padStart(2, "0") + "s"
}
