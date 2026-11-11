// node --test tests/  (Node 22 runs the TypeScript directly)
import assert from "node:assert/strict"
import { test } from "node:test"

import { planPublish } from "../src/lib/publishPlan.ts"

const live = (id: string) => ({ item_id: id, published: true, openFlags: 0 })
const draft = (id: string, openFlags = 0) => ({ item_id: id, published: false, openFlags })

test("publish never takes a live row offline", () => {
  const plan = planPublish([live("mug")], true)
  assert.deepEqual(plan.publishIds, [])
  assert.equal(plan.canPublish, false)
  // it's the other button's job, and only that one's
  assert.deepEqual(plan.offlineIds, ["mug"])
  assert.equal(plan.hint, "That item is already live.")
})

test("a mixed selection publishes the drafts and leaves live rows alone", () => {
  const plan = planPublish([live("mug"), draft("blanket"), live("candle"), draft("tote")], true)
  assert.deepEqual(plan.publishIds, ["blanket", "tote"])
  assert.equal(plan.canPublish, true)
  for (const id of plan.publishIds) assert.ok(!["mug", "candle"].includes(id))
})

test("amber cells block publish but not taking live rows offline", () => {
  const plan = planPublish([draft("blanket", 1), live("mug")], true)
  assert.equal(plan.stillAmber, 1)
  assert.equal(plan.canPublish, false)
  assert.equal(plan.canTakeOffline, true)
  assert.equal(plan.hint, "1 selected item still has amber cells. Confirm or fix them first.")
})

test("nothing ticked", () => {
  const plan = planPublish([], true)
  assert.equal(plan.canPublish, false)
  assert.equal(plan.canTakeOffline, false)
  assert.equal(plan.hint, "Tick rows to publish them.")
})
