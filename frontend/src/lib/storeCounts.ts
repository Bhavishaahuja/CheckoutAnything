// The Agent sidebar's live count for a store. It reads the same counts as the agent's own
// list_stores tool (both come from shop.list_stores on the API), so the two can only disagree
// when the page holds an old copy, which is why the page refetches after every publish and turn.
// No imports on purpose, so tests/storeCounts.test.ts can run it under plain node.

export type StoreCounts = { verified: number; live?: number }

// how many of a store's items an agent can buy. an older API sends no live count, then verified
export function liveCount(counts: StoreCounts): number {
  return counts.live ?? counts.verified
}

// "4 live", or "1 of 4 live" while some verified items wait for the merchant
export function liveLabel(counts: StoreCounts): string {
  const live = liveCount(counts)
  if (live === counts.verified) return live + " live"
  return live + " of " + counts.verified + " live"
}
