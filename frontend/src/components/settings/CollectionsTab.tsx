"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, XCircle, RefreshCw, AlertTriangle } from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

type Proposal = {
  id: number;
  lead_id: number;
  lead_name: string;
  action_type: string;
  autonomy_level: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
  overdue_days?: number;
  amount_overdue?: number;
};

type KPI = {
  total_overdue_dealers: number;
  total_overdue_amount: number;
  pending_proposals: number;
  collected_this_month: number;
};

const TIER_COLOR: Record<string, string> = {
  A2: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  A1: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
};

export default function CollectionsTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const { data: proposals = [], isLoading, refetch } = useQuery({
    queryKey: ["collections-proposals"],
    queryFn: () => apiGet<{ proposals: Proposal[] }>(`${CRM_BASE}/collections/proposals`).then(r => r.proposals ?? []),
  });

  const { data: kpis } = useQuery({
    queryKey: ["collections-kpis"],
    queryFn: () => apiGet<KPI>(`${CRM_BASE}/collections/kpis`),
  });

  const approve = useMutation({
    mutationFn: (id: number) => apiPost(`${CRM_BASE}/collections/proposals/${id}/approve`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["collections-proposals"] }); toast.success("Approved"); },
  });

  const reject = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      apiPost(`${CRM_BASE}/collections/proposals/${id}/reject`, { note }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["collections-proposals"] }); toast.success("Rejected"); },
  });

  const bulkApprove = useMutation({
    mutationFn: (ids: number[]) => apiPost(`${CRM_BASE}/collections/proposals/bulk-approve`, { ledger_ids: ids }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["collections-proposals"] }); setSelected(new Set()); toast.success(`${selected.size} proposals approved`); },
  });

  const scan = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/collections/scan`),
    onSuccess: () => { refetch(); toast.success("AR scan triggered"); },
  });

  const a2Proposals = proposals.filter(p => p.autonomy_level === "A2" && p.status === "pending");
  const allA2Selected = a2Proposals.length > 0 && a2Proposals.every(p => selected.has(p.id));

  function toggleAll() {
    if (allA2Selected) setSelected(new Set());
    else setSelected(new Set(a2Proposals.map(p => p.id)));
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* KPI bar */}
      {kpis && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Overdue Dealers", value: kpis.total_overdue_dealers },
            { label: "Overdue Amount", value: `₹${(kpis.total_overdue_amount / 100000).toFixed(1)}L` },
            { label: "Pending Proposals", value: kpis.pending_proposals },
            { label: "Collected (MTD)", value: `₹${(kpis.collected_this_month / 100000).toFixed(1)}L` },
          ].map(k => (
            <div key={k.label} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3">
              <p className="text-xs text-slate-500 dark:text-slate-400">{k.label}</p>
              <p className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-0.5">{k.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Pending Proposals</h3>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <button
              onClick={() => bulkApprove.mutate(Array.from(selected))}
              disabled={bulkApprove.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {bulkApprove.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              Approve {selected.size}
            </button>
          )}
          <button
            onClick={() => scan.mutate()}
            disabled={scan.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
          >
            {scan.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Run AR Scan
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left w-8">
                <input type="checkbox" checked={allA2Selected} onChange={toggleAll} className="rounded" />
              </th>
              <th className="px-4 py-3 text-left">Dealer</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-center">Level</th>
              <th className="px-4 py-3 text-right">Overdue</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading ? (
              <tr><td colSpan={6} className="py-10 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
            ) : proposals.length === 0 ? (
              <tr><td colSpan={6} className="py-10 text-center text-sm text-slate-400">No pending proposals. Run AR scan to generate.</td></tr>
            ) : proposals.map(p => (
              <tr key={p.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                <td className="px-4 py-3">
                  {p.autonomy_level === "A2" && p.status === "pending" && (
                    <input
                      type="checkbox"
                      checked={selected.has(p.id)}
                      onChange={() => setSelected(prev => { const n = new Set(prev); n.has(p.id) ? n.delete(p.id) : n.add(p.id); return n; })}
                      className="rounded"
                    />
                  )}
                </td>
                <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">{p.lead_name}</td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400 capitalize">{p.action_type.replace(/_/g, " ")}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${TIER_COLOR[p.autonomy_level] ?? ""}`}>
                    {p.autonomy_level}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-400">
                  {p.overdue_days != null ? `${p.overdue_days}d` : "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => approve.mutate(p.id)}
                      disabled={approve.isPending}
                      title="Approve"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => {
                        const note = prompt("Reason for rejection:");
                        if (note) reject.mutate({ id: p.id, note });
                      }}
                      title="Reject"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors"
                    >
                      <XCircle className="h-4 w-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {proposals.some(p => p.autonomy_level === "A1") && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          A1 proposals (15+ days overdue) require individual review and cannot be batch-approved.
        </div>
      )}
    </div>
  );
}
