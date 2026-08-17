"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, XCircle, RefreshCw, RotateCcw, GitMerge,
  AlertTriangle, CheckCircle, Clock,
} from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

// ─── Types ────────────────────────────────────────────────────────────────────

type Voucher = {
  id: number;
  zoho_books_ref: string | null;
  voucher_type: string;
  voucher_type_label: string;
  voucher_date: string;
  party_name: string | null;
  narration: string | null;
  amount: string | null;
  mapped_ledger: string | null;
  status: string;
  error: string | null;
  retry_count: number;
  tally_voucher_id: string | null;
  posted_at: string | null;
};

type KPI = {
  last_sync_at: string | null;
  drift_inr: number | null;
  drift_pct: number | null;
  drift_alert: boolean;
  pending_review_count: number;
  posted_count: number;
  posted_amount_inr: number;
  success_rate_pct: number;
  failed_retryable_count: number;
  failed_exhausted_count: number;
  status_counts: Record<string, number>;
};

const STATUS_COLOR: Record<string, string> = {
  staged:           "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300",
  pending_approval: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  approved:         "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  posting:          "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300",
  posted:           "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  failed:           "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
  rejected:         "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
};

const VOUCHER_TYPE_OPTIONS = [
  "sales_invoice", "purchase_invoice", "receipt", "payment",
  "credit_note", "debit_note", "journal", "contra",
];

// ─── Main Tab ─────────────────────────────────────────────────────────────────

export default function BooksSyncTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const qc = useQueryClient();
  const [view, setView] = useState<"queue" | "history">("queue");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [typeFilter, setTypeFilter] = useState("");

  const { data: staged, isLoading } = useQuery({
    queryKey: ["books-sync-staged", typeFilter],
    queryFn: () => apiGet<{ items: Voucher[]; pending_amount_inr: number; status_counts: Record<string, number> }>(
      `${CRM_BASE}/books-sync/staged?status=all_pending${typeFilter ? `&voucher_type=${typeFilter}` : ""}&limit=200`
    ),
    enabled: view === "queue",
  });

  const { data: history, isLoading: histLoading } = useQuery({
    queryKey: ["books-sync-history"],
    queryFn: () => apiGet<{ items: Voucher[]; total: number }>(
      `${CRM_BASE}/books-sync/history?days=30&limit=200`
    ),
    enabled: view === "history",
  });

  const { data: kpis } = useQuery({
    queryKey: ["books-sync-kpis"],
    queryFn: () => apiGet<KPI>(`${CRM_BASE}/books-sync/kpis?days=30`),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["books-sync-staged"] });
    qc.invalidateQueries({ queryKey: ["books-sync-history"] });
    qc.invalidateQueries({ queryKey: ["books-sync-kpis"] });
  };

  const bulkApprove = useMutation({
    mutationFn: (ids: number[]) => apiPost<{ approved_count: number; total_amount_inr: number }>(
      `${CRM_BASE}/books-sync/staged/bulk-approve`, { staging_ids: ids }
    ),
    onSuccess: (data) => {
      invalidate();
      setSelected(new Set());
      toast.success(`${data.approved_count} vouchers approved — ₹${data.total_amount_inr.toLocaleString("en-IN")} queued for Tally`);
    },
  });

  const approve = useMutation({
    mutationFn: (id: number) => apiPost(`${CRM_BASE}/books-sync/staged/${id}/approve`, {}),
    onSuccess: () => { invalidate(); toast.success("Voucher approved"); },
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiPost(`${CRM_BASE}/books-sync/staged/${id}/reject`, { reason }),
    onSuccess: () => { invalidate(); toast.success("Voucher rejected"); },
  });

  const syncNow = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/books-sync/sync`, {}),
    onSuccess: () => { invalidate(); toast.success("Sync triggered — staged vouchers will appear shortly"); },
  });

  const reconcile = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/books-sync/reconcile`, { days: 30 }),
    onSuccess: () => { invalidate(); toast.success("Reconciliation queued"); },
  });

  const retryFailed = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/books-sync/retry`),
    onSuccess: () => { invalidate(); toast.success("Retry queued for failed vouchers"); },
  });

  const vouchers = staged?.items ?? [];
  const pendingAll = vouchers;
  const allSelected = pendingAll.length > 0 && pendingAll.every(v => selected.has(v.id));

  function toggleAll() {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(pendingAll.map(v => v.id)));
  }

  return (
    <div className="space-y-6 max-w-5xl">
      {/* KPI bar */}
      {kpis && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Pending Review", value: kpis.pending_review_count, accent: kpis.pending_review_count > 0 ? "text-amber-600" : null },
              { label: "Posted (30d)", value: kpis.posted_count, sub: `₹${(kpis.posted_amount_inr / 100000).toFixed(1)}L` },
              { label: "Success Rate", value: `${kpis.success_rate_pct}%`, accent: kpis.success_rate_pct < 95 ? "text-rose-500" : "text-emerald-500" },
              { label: "Failed / Stuck", value: kpis.failed_retryable_count + kpis.failed_exhausted_count,
                sub: kpis.failed_exhausted_count > 0 ? `${kpis.failed_exhausted_count} exhausted` : null,
                accent: kpis.failed_exhausted_count > 0 ? "text-rose-500" : null },
            ].map(k => (
              <div key={k.label} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3">
                <p className="text-xs text-slate-500 dark:text-slate-400">{k.label}</p>
                <p className={`text-xl font-bold mt-0.5 ${k.accent ?? "text-slate-900 dark:text-slate-100"}`}>{k.value}</p>
                {k.sub && <p className="text-xs text-slate-400 mt-0.5">{k.sub}</p>}
              </div>
            ))}
          </div>

          {kpis.drift_alert && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
              <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              Tally drift detected: ₹{kpis.drift_inr?.toLocaleString("en-IN")} ({kpis.drift_pct}%). Run reconciliation to investigate.
            </div>
          )}

          {kpis.last_sync_at && (
            <p className="text-xs text-slate-400">
              Last sync: {new Date(kpis.last_sync_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1">
          {(["queue", "history"] as const).map(v => (
            <button key={v} onClick={() => setView(v)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-colors ${
                view === v ? "bg-violet-600 text-white" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}>
              {v === "queue" ? "Pending Queue" : "History"}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {view === "queue" && (
            <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
              className="text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-slate-700 dark:text-slate-300">
              <option value="">All types</option>
              {VOUCHER_TYPE_OPTIONS.map(t => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
            </select>
          )}
          {selected.size > 0 && (
            <button onClick={() => bulkApprove.mutate(Array.from(selected))} disabled={bulkApprove.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
              {bulkApprove.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              Approve {selected.size}
            </button>
          )}
          <button onClick={() => syncNow.mutate()} disabled={syncNow.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50">
            {syncNow.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Sync Now
          </button>
          <button onClick={() => reconcile.mutate()} disabled={reconcile.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50">
            {reconcile.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitMerge className="h-3.5 w-3.5" />}
            Reconcile
          </button>
          {kpis && kpis.failed_retryable_count > 0 && (
            <button onClick={() => retryFailed.mutate()} disabled={retryFailed.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-rose-300 dark:border-rose-700 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 disabled:opacity-50">
              {retryFailed.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              Retry Failed ({kpis.failed_retryable_count})
            </button>
          )}
        </div>
      </div>

      {/* Queue Table */}
      {view === "queue" && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          {staged?.pending_amount_inr != null && staged.pending_amount_inr > 0 && (
            <div className="px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700 text-xs text-slate-500">
              Total pending: <span className="font-semibold text-slate-700 dark:text-slate-300">₹{staged.pending_amount_inr.toLocaleString("en-IN")}</span>
            </div>
          )}
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 w-8">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} className="rounded" />
                </th>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Party</th>
                <th className="px-4 py-3 text-right">Amount (₹)</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {isLoading ? (
                <tr><td colSpan={7} className="py-12 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
              ) : vouchers.length === 0 ? (
                <tr><td colSpan={7} className="py-12 text-center text-sm text-slate-400">Queue empty. Click "Sync Now" to pull from Zoho Books.</td></tr>
              ) : vouchers.map(v => (
                <tr key={v.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="px-4 py-3">
                    {(v.status === "staged" || v.status === "pending_approval") && (
                      <input type="checkbox" checked={selected.has(v.id)}
                        onChange={() => setSelected(prev => { const n = new Set(prev); n.has(v.id) ? n.delete(v.id) : n.add(v.id); return n; })}
                        className="rounded" />
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {new Date(v.voucher_date).toLocaleDateString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-slate-700 dark:text-slate-300 capitalize text-xs">
                    {v.voucher_type_label}
                  </td>
                  <td className="px-4 py-3 text-slate-700 dark:text-slate-300 max-w-[160px] truncate">
                    {v.party_name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-slate-900 dark:text-slate-100">
                    {v.amount ? parseFloat(v.amount).toLocaleString("en-IN") : "—"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold capitalize ${STATUS_COLOR[v.status] ?? ""}`}>
                      {v.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {(v.status === "staged" || v.status === "pending_approval") && (
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => approve.mutate(v.id)} disabled={approve.isPending} title="Approve"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20">
                          <CheckCircle2 className="h-4 w-4" />
                        </button>
                        <button onClick={() => { const r = prompt("Rejection reason:"); if (r) reject.mutate({ id: v.id, reason: r }); }} title="Reject"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20">
                          <XCircle className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* History Table */}
      {view === "history" && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Party</th>
                <th className="px-4 py-3 text-right">Amount (₹)</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-left">Tally ID / Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {histLoading ? (
                <tr><td colSpan={6} className="py-12 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
              ) : (history?.items ?? []).length === 0 ? (
                <tr><td colSpan={6} className="py-12 text-center text-sm text-slate-400">No history in last 30 days.</td></tr>
              ) : (history?.items ?? []).map(v => (
                <tr key={v.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {new Date(v.voucher_date).toLocaleDateString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400 capitalize">
                    {v.voucher_type_label}
                  </td>
                  <td className="px-4 py-3 text-slate-700 dark:text-slate-300 max-w-[140px] truncate">{v.party_name ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-medium text-slate-900 dark:text-slate-100">
                    {v.amount ? parseFloat(v.amount).toLocaleString("en-IN") : "—"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${STATUS_COLOR[v.status] ?? ""}`}>
                      {v.status === "posted" ? <><CheckCircle className="h-3 w-3 inline mr-0.5" />posted</> : v.status === "failed" ? <><XCircle className="h-3 w-3 inline mr-0.5 text-rose-400" />failed</> : v.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-slate-400 max-w-[200px] truncate">
                    {v.tally_voucher_id ?? v.error ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
