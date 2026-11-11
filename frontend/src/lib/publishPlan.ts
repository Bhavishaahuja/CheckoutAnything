// What the catalog toolbar's two bulk buttons would do with the ticked rows. Publish only ever
// publishes: a ticked row that is already live is left alone, never taken offline. Taking rows
// offline is its own button, and it only touches the ticked rows that are live.
// No imports on purpose, so tests/publishPlan.test.ts can run it under plain node.

export type PlanRow = {
  item_id: string
  published: boolean
  // open amber cells on the row. an item with one can't be published until it's confirmed
  openFlags: number
}

export type PublishPlan = {
  // ids the Publish button sends with published: true
  publishIds: string[]
  // ids the Take offline button sends with published: false
  offlineIds: string[]
  // ticked rows that would be published but still have amber cells. any of these blocks Publish
  stillAmber: number
  canPublish: boolean
  canTakeOffline: boolean
  // the line next to the buttons, or null
  hint: string | null
}

export function planPublish(selected: PlanRow[], editable: boolean): PublishPlan {
  const publishIds: string[] = []
  const offlineIds: string[] = []
  let stillAmber = 0
  for (const row of selected) {
    if (row.published) {
      offlineIds.push(row.item_id)
    } else {
      publishIds.push(row.item_id)
      if (row.openFlags > 0) stillAmber += 1
    }
  }

  let hint: string | null = null
  if (editable && selected.length === 0) hint = "Tick rows to publish them."
  else if (selected.length > 0 && publishIds.length === 0) {
    hint = selected.length === 1 ? "That item is already live." : "Everything ticked is already live."
  }
  if (stillAmber > 0) {
    hint =
      stillAmber +
      (stillAmber === 1 ? " selected item still has" : " selected items still have") +
      " amber cells. Confirm or fix them first."
  }

  return {
    publishIds,
    offlineIds,
    stillAmber,
    canPublish: publishIds.length > 0 && stillAmber === 0,
    // amber cells only stop publishing. taking a live item offline is always allowed
    canTakeOffline: offlineIds.length > 0,
    hint,
  }
}
