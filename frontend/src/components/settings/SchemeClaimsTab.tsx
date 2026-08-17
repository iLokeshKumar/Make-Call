"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, XCircle, RefreshCw, Send, Banknote,
  AlertTriangle, Clock, ChevronDown, ChevronUp, Plus,
} from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

// ─── Types ────────────────────────────────────────────────────────────────────

type Claim = {
  id: number;
  scheme_id: number;
  scheme_code: string | null;
  scheme_name: string | null;
  submission_deadline: string | null;
  total_qualifying_units: number;
  total_claimed_inr: number;
  settled_amount_inr: number | null;
  accuracy_pct: number | null;
  status: string;
  reviewer_note: string | null;
  rejection_reason: string | null;
  created_at: string;
};

type KPI = {
  avg_accuracy_pct: number | null;
  meets_a2_gate: boolean | null;
  a2_gate_threshold_pct: number;
  settled_claim_count: number;
  total_claimable_inr: number;
  total_settled_inr: number;
  total_variance_inr: number;
  pending_approval_count: number;
  pipeline_by_status: Record<string, number>;
  upcoming_deadlines: { scheme_code: string; scheme_name: string; deadline: string; days_remaining: number }[];
};

const STATUS_STEPS = ["proposed", "approved", "submitted", "settled"] as const;

const STATUS_COLOR: Record<string, string> = {
  proposed:    "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  approved:    "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  submitted:   "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300",
  settled:     "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  rejected:    "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
  disputed:    "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
};

// ─── SubmitDialog ─────────────────────────────────────────────────────────────

function SubmitDialog({ claim, onClose, onSubmit }: {
  claim: Claim;
  onClose: () => void;
  onSubmit: (ref: string) => void;
}) {
  const [ref, setRef] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 w-full max-w-sm shadow-xl border border-slate-200 dark:border-slate-700 space-y-4">
        <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">Mark as Submitted</h3>
        <p className="text-sm text-slate-500">Claim <strong>{claim.scheme_code}</strong> — ₹{claim.total_claimed_inr.toLocaleString("en-IN")}</p>
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Submission Reference</label>
          <input
            value={ref}
            onChange={e => setRef(e.target.value)}
            placeholder="e.g. SAMSUNG-2026-Q1-REF001"
            className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
          <button
            disabled={!ref.trim()}
            onClick={() => onSubmit(ref.trim())}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" /> Submit
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── SettleDialog ─────────────────────────────────────────────────────────────

function SettleDialog({ claim, onClose, onSettle }: {
  claim: Claim;
  onClose: () => void;
  onSettle: (amount: number, ref: string) => void;
}) {
  const [amount, setAmount] = useState("");
  const [ref, setRef] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 w-full max-w-sm shadow-xl border border-slate-200 dark:border-slate-700 space-y-4">
        <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">Record Settlement</h3>
        <p className="text-sm text-slate-500">Claimed: ₹{claim.total_claimed_inr.toLocaleString("en-IN")}</p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Settled Amount (₹)</label>
            <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00"
              className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Settlement Reference</label>
            <input value={ref} onChange={e => setRef(e.target.value)} placeholder="Vendor settlement ref"
              className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
          <button
            disabled={!amount || !ref.trim()}
            onClick={() => onSettle(parseFloat(amount), ref.trim())}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            <Banknote className="h-3.5 w-3.5" /> Settle
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Tab ─────────────────────────────────────────────────────────────────

export default function SchemeClaimsTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("proposed");
  const [submitClaim, setSubmitClaim] = useState<Claim | null>(null);
  const [settleClaim, setSettleClaim] = useState<Claim | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: claimsData, isLoading } = useQuery({
    queryKey: ["scheme-claims", statusFilter],
    queryFn: () => apiGet<{ items: Claim[]; status_counts: Record<string, number>; pending_value_inr: number }>(
      `${CRM_BASE}/scheme-claims/claims?status=${statusFilter}&limit=100`
    ),
  });

  const { data: kpis } = useQuery({
    queryKey: ["scheme-claims-kpis"],
    queryFn: () => apiGet<KPI>(`${CRM_BASE}/scheme-claims/kpis?days=90`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["scheme-claims"] });
    qc.invalidateQueries({ queryKey: ["scheme-claims-kpis"] });
  };

  const approve = useMutation({
    mutationFn: (id: number) => apiPost(`${CRM_BASE}/scheme-claims/claims/${id}/approve`, {}),
    onSuccess: () => { invalidate(); toast.success("Claim approved"); },
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiPost(`${CRM_BASE}/scheme-claims/claims/${id}/reject`, { reason }),
    onSuccess: () => { invalidate(); toast.success("Claim rejected"); },
  });

  const submit = useMutation({
    mutationFn: ({ id, ref }: { id: number; ref: string }) =>
      apiPost(`${CRM_BASE}/scheme-claims/claims/${id}/submit`, { submission_ref: ref }),
    onSuccess: () => { invalidate(); setSubmitClaim(null); toast.success("Marked as submitted"); },
  });

  const settle = useMutation({
    mutationFn: ({ id, amount, ref }: { id: number; amount: number; ref: string }) =>
      apiPost(`${CRM_BASE}/scheme-claims/claims/${id}/settle`, { settled_amount_inr: amount, settlement_ref: ref }),
    onSuccess: () => { invalidate(); setSettleClaim(null); toast.success("Settlement queued"); },
  });

  const scan = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/scheme-claims/scan`),
    onSuccess: () => { invalidate(); toast.success("Scheme scan triggered"); },
  });

  const claims = claimsData?.items ?? [];
  const statusCounts = claimsData?.status_counts ?? {};

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Dialogs */}
      {submitClaim && (
        <SubmitDialog
          claim={submitClaim}
          onClose={() => setSubmitClaim(null)}
          onSubmit={ref => submit.mutate({ id: submitClaim.id, ref })}
        />
      )}
      {settleClaim && (
        <SettleDialog
          claim={settleClaim}
          onClose={() => setSettleClaim(null)}
          onSettle={(amount, ref) => settle.mutate({ id: settleClaim.id, amount, ref })}
        />
      )}

      {/* KPI bar */}
      {kpis && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Claim Accuracy", value: kpis.avg_accuracy_pct != null ? `${kpis.avg_accuracy_pct}%` : "—",
                sub: kpis.meets_a2_gate === true ? "✓ Meets 97% gate" : kpis.meets_a2_gate === false ? "⚠ Below 97% gate" : null,
                accent: kpis.meets_a2_gate === false ? "text-rose-500" : "text-emerald-500" },
              { label: "Pending Approval", value: kpis.pending_approval_count, sub: null, accent: null },
              { label: "Claimable (90d)", value: `₹${(kpis.total_claimable_inr / 100000).toFixed(1)}L`, sub: null, accent: null },
              { label: "Settled (90d)", value: `₹${(kpis.total_settled_inr / 100000).toFixed(1)}L`,
                sub: kpis.total_variance_inr !== 0 ? `Variance ₹${Math.abs(kpis.total_variance_inr).toLocaleString("en-IN")}` : null,
                accent: kpis.total_variance_inr < 0 ? "text-rose-500" : "text-slate-400" },
            ].map(k => (
              <div key={k.label} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3">
                <p className="text-xs text-slate-500 dark:text-slate-400">{k.label}</p>
                <p className="text-xl font-bold text-slate-900 dark:text-slate-100 mt-0.5">{k.value}</p>
                {k.sub && <p className={`text-xs mt-0.5 ${k.accent ?? "text-slate-400"}`}>{k.sub}</p>}
              </div>
            ))}
          </div>
          {kpis.upcoming_deadlines.length > 0 && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-300">
              <Clock className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>
                <strong>Upcoming deadlines:</strong>{" "}
                {kpis.upcoming_deadlines.map(d => `${d.scheme_code} (${d.days_remaining}d)`).join(" · ")}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Status filter tabs */}
        <div className="flex gap-1 flex-wrap">
          {(["proposed", "approved", "submitted", "settled", "rejected", "all"] as const).map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors ${
                statusFilter === s
                  ? "bg-violet-600 text-white"
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              {s}
              {statusCounts[s] != null && s !== "all" && (
                <span className="ml-1 opacity-70">({statusCounts[s]})</span>
              )}
            </button>
          ))}
        </div>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
        >
          {scan.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Run Scan
        </button>
      </div>

      {/* Claims table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Scheme</th>
              <th className="px-4 py-3 text-right">Claimed (₹)</th>
              <th className="px-4 py-3 text-right">Units</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-center">Accuracy</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading ? (
              <tr><td colSpan={6} className="py-12 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
            ) : claims.length === 0 ? (
              <tr><td colSpan={6} className="py-12 text-center text-sm text-slate-400">No claims with status "{statusFilter}". Run scan to generate proposals.</td></tr>
            ) : claims.map(c => (
              <>
                <tr key={c.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                      className="flex items-center gap-1.5 text-left"
                    >
                      {expandedId === c.id ? <ChevronUp className="h-3.5 w-3.5 text-slate-400" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
                      <div>
                        <div className="font-semibold text-slate-900 dark:text-slate-100">{c.scheme_code ?? `#${c.scheme_id}`}</div>
                        <div className="text-xs text-slate-400 truncate max-w-[180px]">{c.scheme_name}</div>
                      </div>
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-slate-900 dark:text-slate-100">
                    {c.total_claimed_inr.toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-500">{c.total_qualifying_units}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${STATUS_COLOR[c.status] ?? ""}`}>
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-slate-500">
                    {c.accuracy_pct != null ? (
                      <span className={c.accuracy_pct >= 97 ? "text-emerald-600 dark:text-emerald-400 font-semibold" : "text-rose-600 dark:text-rose-400 font-semibold"}>
                        {c.accuracy_pct}%
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {c.status === "proposed" && (
                        <>
                          <button onClick={() => approve.mutate(c.id)} title="Approve" disabled={approve.isPending}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors">
                            <CheckCircle2 className="h-4 w-4" />
                          </button>
                          <button onClick={() => { const r = prompt("Rejection reason:"); if (r) reject.mutate({ id: c.id, reason: r }); }} title="Reject"
                            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors">
                            <XCircle className="h-4 w-4" />
                          </button>
                        </>
                      )}
                      {c.status === "approved" && (
                        <button onClick={() => setSubmitClaim(c)} title="Mark Submitted"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors">
                          <Send className="h-4 w-4" />
                        </button>
                      )}
                      {(c.status === "submitted" || c.status === "acknowledged") && (
                        <button onClick={() => setSettleClaim(c)} title="Record Settlement"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors">
                          <Banknote className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
                {expandedId === c.id && (
                  <tr key={`${c.id}-expand`} className="bg-slate-50 dark:bg-slate-800/30">
                    <td colSpan={6} className="px-8 py-3 text-xs text-slate-500 space-y-1">
                      {c.submission_deadline && (
                        <p>Deadline: <span className="font-medium text-slate-700 dark:text-slate-300">{new Date(c.submission_deadline).toLocaleDateString()}</span></p>
                      )}
                      {c.settled_amount_inr != null && (
                        <p>Settled: <span className="font-medium text-slate-700 dark:text-slate-300">₹{c.settled_amount_inr.toLocaleString("en-IN")}</span></p>
                      )}
                      {c.reviewer_note && <p>Note: {c.reviewer_note}</p>}
                      {c.rejection_reason && (
                        <p className="text-rose-500">Rejected: {c.rejection_reason}</p>
                      )}
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {statusFilter === "proposed" && kpis?.meets_a2_gate === false && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          Claim accuracy below 97% — AI autonomy gate is closed. All claims require individual review.
        </div>
      )}
    </div>
  );
}
