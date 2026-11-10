// Defend: PayPal disputes on captured orders, answered with the records Check kept. Everything
// here is read from and done by the Check service, the API only passes it through.

import type { ColDef, GetRowIdParams, RowClickedEvent } from "ag-grid-community"
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react"
import { Check, FileText, RefreshCw, Send } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Card, CopyId, ErrorNote, Pill } from "@/components/bits"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { dateAndTime, decisionTime, money } from "@/lib/format"
import { calmTheme } from "@/lib/gridTheme"
import type { Dispute, DisputeEvidence } from "@/lib/types"

// PayPal's own strings, made readable: WAITING_FOR_SELLER_RESPONSE -> Waiting for seller response
function plain(code: string | null) {
  if (!code) return ""
  const words = code.toLowerCase().split("_").join(" ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function EvidenceCell({ data }: CustomCellRendererProps<Dispute>) {
  if (!data) return null
  if (data.evidence_submitted) {
    return (
      <Pill tone="ok">
        <Check className="size-3.5" strokeWidth={3} /> Submitted
      </Pill>
    )
  }
  if (data.has_summary) return <Pill tone="info">Drafted</Pill>
  return <Pill tone="muted">Not started</Pill>
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-[13px]">{children}</dd>
    </div>
  )
}

export function DisputesPage({ active }: { active: boolean }) {
  const [disputes, setDisputes] = useState<Dispute[]>([])
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState<"sync" | "evidence" | "redraft" | "submit" | null>(null)
  const [evidence, setEvidence] = useState<DisputeEvidence | null>(null)

  const fail = (problem: unknown, fallback: string) => {
    setError(problem instanceof Error ? problem.message : fallback)
  }

  const load = useCallback(async () => {
    try {
      setDisputes(await api.listDisputes())
      setError(null)
    } catch (problem) {
      fail(problem, "Couldn't load disputes")
    }
  }, [])

  useEffect(() => {
    if (active) void load()
  }, [active, load])

  const sync = async () => {
    setBusy("sync")
    setNote(null)
    try {
      const result = await api.syncDisputes()
      let message = "Asked PayPal about " + result.orders_checked + " captured " + (result.orders_checked === 1 ? "order" : "orders")
      message += ": " + result.created + " new, " + result.updated + " updated."
      if (result.errors.length > 0) message += " " + result.errors.length + " couldn't be checked."
      setNote(message)
      await load()
    } catch (problem) {
      fail(problem, "The sync failed")
    } finally {
      setBusy(null)
    }
  }

  // the first look at a dispute drafts its summary, which is a Claude call
  const open = async (dispute: Dispute) => {
    setBusy("evidence")
    setNote(null)
    try {
      setEvidence(await api.disputeEvidence(dispute.id))
      setError(null)
      await load()
    } catch (problem) {
      fail(problem, "Couldn't build the evidence")
    } finally {
      setBusy(null)
    }
  }

  const redraft = async () => {
    if (!evidence) return
    setBusy("redraft")
    try {
      setEvidence(await api.redraftDispute(evidence.dispute.id))
      setError(null)
    } catch (problem) {
      fail(problem, "Couldn't redraft the summary")
    } finally {
      setBusy(null)
    }
  }

  const submit = async () => {
    if (!evidence) return
    setBusy("submit")
    try {
      const updated = await api.submitDisputeEvidence(evidence.dispute.id)
      setEvidence({ ...evidence, dispute: updated })
      setNote("Evidence filed with PayPal for " + updated.paypal_dispute_id + ".")
      setError(null)
      await load()
    } catch (problem) {
      fail(problem, "PayPal didn't take the evidence")
    } finally {
      setBusy(null)
    }
  }

  const columnDefs = useMemo<ColDef<Dispute>[]>(
    () => [
      {
        headerName: "PayPal dispute",
        field: "paypal_dispute_id",
        flex: 1.4,
        minWidth: 200,
        cellRenderer: (params: CustomCellRendererProps<Dispute>) => <CopyId value={params.value} />,
      },
      { headerName: "Check order", field: "order_id", width: 124, type: "rightAligned", cellClass: "tabular-nums" },
      { headerName: "Reason", field: "reason", flex: 1, minWidth: 150, valueFormatter: (params) => plain(params.value) },
      { headerName: "PayPal status", field: "status", flex: 1.4, minWidth: 200, valueFormatter: (params) => plain(params.value) },
      {
        headerName: "Answer by",
        field: "seller_response_due_at",
        width: 150,
        valueFormatter: (params) => dateAndTime(params.value),
        cellClass: "tabular-nums",
      },
      { headerName: "Evidence", field: "evidence_submitted", width: 140, cellRenderer: EvidenceCell },
    ],
    []
  )

  const packet = evidence ? evidence.packet : null
  const shown = evidence ? evidence.dispute : null

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Disputes</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            When a buyer disputes a captured order, Checkout Anything answers with its own records: what the buyer
            asked for, what was ordered, how it was checked and who released the money.
          </p>
        </div>
        <Button variant="outline" onClick={sync} disabled={busy !== null}>
          <RefreshCw className={busy === "sync" ? "spin-slow" : undefined} /> {busy === "sync" ? "Asking PayPal" : "Sync with PayPal"}
        </Button>
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}
      {note && <p className="rounded-lg bg-info-soft px-3 py-2 text-[13px] text-primary">{note}</p>}

      <Card className="flex h-[320px] flex-col overflow-hidden">
        <AgGridReact<Dispute>
          theme={calmTheme}
          rowData={disputes}
          columnDefs={columnDefs}
          defaultColDef={{ sortable: true, resizable: true, suppressMovable: true }}
          getRowId={(params: GetRowIdParams<Dispute>) => String(params.data.id)}
          onRowClicked={(event: RowClickedEvent<Dispute>) => {
            if (event.data && busy === null) void open(event.data)
          }}
          rowClass="cursor-pointer"
          suppressCellFocus
          overlayNoRowsTemplate='<span style="color: var(--muted-foreground); font-size: 13px">No disputes. Sync with PayPal to look for new ones.</span>'
        />
      </Card>

      {busy === "evidence" && !evidence && <p className="text-[13px] text-muted-foreground">Building the evidence...</p>}

      {evidence && shown && packet && (
        <Card className="flex flex-col gap-5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold">
              <FileText className="size-4 text-muted-foreground" /> Evidence for {shown.paypal_dispute_id}
            </h2>
            <div className="flex items-center gap-2">
              {shown.evidence_submitted ? (
                <Pill tone="ok">
                  <Check className="size-3.5" strokeWidth={3} /> Submitted {dateAndTime(shown.evidence_submitted_at)}
                </Pill>
              ) : (
                <>
                  <Button size="sm" variant="outline" onClick={redraft} disabled={busy !== null}>
                    {busy === "redraft" ? "Redrafting" : "Redraft summary"}
                  </Button>
                  <Button size="sm" onClick={submit} disabled={busy !== null}>
                    <Send /> {busy === "submit" ? "Sending" : "Submit to PayPal"}
                  </Button>
                </>
              )}
            </div>
          </div>

          <div>
            <div className="text-xs text-muted-foreground">Summary for the PayPal reviewer, drafted by Claude from the records below</div>
            <p className="mt-1.5 rounded-lg bg-muted px-3.5 py-3 text-[14px] leading-relaxed">{evidence.summary}</p>
          </div>

          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label="What the buyer asked for">{packet.mandate?.raw_request || "Not recorded"}</Fact>
            <Fact label="What was ordered">
              {packet.order?.total ? money(packet.order.total, packet.order.currency || "USD") : ""}
              {packet.order?.store ? " at " + packet.order.store : ""}
            </Fact>
            <Fact label="How it was checked">
              {packet.intent_check
                ? plain(packet.intent_check.verdict || "") +
                  (packet.intent_check.risk_score !== null && packet.intent_check.risk_score !== undefined
                    ? ", risk " + packet.intent_check.risk_score + " of 100"
                    : "") +
                  (packet.intent_check.reason ? ". " + packet.intent_check.reason : "")
                : "No check was saved"}
            </Fact>
            <Fact label="Who released the money">
              {packet.decision?.released_by ? plain(packet.decision.released_by) : "Not recorded"}
              {packet.decision?.decision_ms !== null && packet.decision?.decision_ms !== undefined
                ? ", decided in " + decisionTime(packet.decision.decision_ms)
                : ""}
            </Fact>
          </dl>
        </Card>
      )}
    </div>
  )
}
