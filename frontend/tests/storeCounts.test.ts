import assert from "node:assert/strict"
import { test } from "node:test"

import { liveCount, liveLabel } from "../src/lib/storeCounts.ts"

test("all published reads as N live", () => {
  assert.equal(liveLabel({ verified: 6, live: 6 }), "6 live")
})

test("some waiting reads as N of M live", () => {
  assert.equal(liveLabel({ verified: 6, live: 5 }), "5 of 6 live")
  assert.equal(liveLabel({ verified: 3, live: 0 }), "0 of 3 live")
})

test("an older API with no live count falls back to verified", () => {
  assert.equal(liveCount({ verified: 4 }), 4)
})
