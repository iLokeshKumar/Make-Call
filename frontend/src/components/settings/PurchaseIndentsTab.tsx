"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, XCircle, RefreshCw } from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

type Indent = {
  id: number;
  indent_number: string | null;
  status: string;
  autonomy_level: string;
  action_ledger_id: number | null;
  total_value_inr: string;
  created_at: string;
};

type PurchaseKPIResponse = {
  indents: { pending_approval: number; approved: number; total: number; total_value_proposed_inr: number };
};

export default function PurchaseIndentsTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const { data: indents = [], isLoading } = useQuery({
    queryKey: ["purchase-indents"],
    queryFn: () => apiGet<{ indents: Indent[] }>(`${CRM_BASE}/purchase/indents`).then(r => r.indents ?? []),
  });

  const { data: kpisRaw } = useQuery({
    queryKey: ["purchase-kpis"],
    queryFn: () => apiGet<PurchaseKPIResponse>(`${CRM_BASE}/purchase/kpis`),
  });
  const kpis = kpisRaw?.indents;

  const approve = useMutation({
    mutationFn: (id: number) => apiPost(`${CRM_BASE}/purchase/indents/${id}/approve`, { approved_by_user_id: 0 }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["purchase-indents"] }); toast.success("Indent approved"); },
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      apiPost(`${CRM_BASE}/purchase/indents/${id}/reject`, { rejected_by_user_id: 0, reason }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["purchase-indents"] }); toast.success("Indent rejected"); },
  });

  const bulkApprove = useMutation({
    mutationFn: (ledgerIds: number[]) =>
      apiPost(`${CRM_BASE}/purchase/indents/bulk-approve`, { ledger_ids: ledgerIds, approved_by_user_id: 0 }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["purchase-indents"] }); setSelected(new Set()); toast.success(`${selected.size} indents approved`); },
  });

  const scan = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/purchase/indents/scan`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["purchase-indents"] }); toast.success("Indent scan triggered"); },
  });

  const pendingA2 = indents.filter(i => i.autonomy_level === "A2" && i.status === "proposed" && i.action_ledger_id != null);
  const allSelected = pendingA2.length > 0 && pendingA2.every(i => selected.has(i.action_ledger_id!));

  return (
    <div className="space-y-6 max-w-4xl">
      {kpis && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Pending Approval", value: kpis.pending_approval },
            { label: "Approved", value: kpis.approved },
            { label: "Total Indents", value: kpis.total },
          ].map(k => (
            <div key={k.label} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3">
              <p className="text-xs text-slate-500">{k.label}</p>
              <p className="text-2xl font-bold text-slate-900 dark:text-slate-100 mt-0.5">{k.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Indent Queue</h3>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <button onClick={() => bulkApprove.mutate(Array.from(selected).map(Number))} disabled={bulkApprove.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
              {bulkApprove.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              Approve {selected.size}
            </button>
          )}
          <button onClick={() => scan.mutate()} disabled={scan.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 disabled:opacity-50">
            {scan.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Scan
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 w-8">
                <input type="checkbox" checked={allSelected} onChange={() => allSelected ? setSelected(new Set()) : setSelected(new Set(pendingA2.map(i => i.action_ledger_id!)))} className="rounded" />
              </th>
              <th className="px-4 py-3 text-left">Indent #</th>
              <th className="px-4 py-3 text-right">Value</th>
              <th className="px-4 py-3 text-center">Level</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading ? (
              <tr><td colSpan={6} className="py-10 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
            ) : indents.length === 0 ? (
              <tr><td colSpan={6} className="py-10 text-center text-sm text-slate-400">No pending indents.</td></tr>
            ) : indents.map(i => (
              <tr key={i.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-4 py-3">
                  {i.autonomy_level === "A2" && i.status === "proposed" && i.action_ledger_id != null && (
                    <input type="checkbox" checked={selected.has(i.action_ledger_id)}
                      onChange={() => setSelected(prev => { const n = new Set(prev); n.has(i.action_ledger_id!) ? n.delete(i.action_ledger_id!) : n.add(i.action_ledger_id!); return n; })}
                      className="rounded" />
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{i.indent_number ?? `#${i.id}`}</td>
                <td className="px-4 py-3 text-right font-semibold text-slate-800 dark:text-slate-200">
                  ₹{Number(i.total_value_inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </td>
                <td className="px-4 py-3 text-center">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${i.autonomy_level === "A1" ? "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300" : "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"}`}>
                    {i.autonomy_level}
                  </span>
                </td>
                <td className="px-4 py-3 text-center capitalize text-xs text-slate-500">{i.status}</td>
                <td className="px-4 py-3 text-right">
                  {i.status === "proposed" && (
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => approve.mutate(i.id)} title="Approve"
                        className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20">
                        <CheckCircle2 className="h-4 w-4" />
                      </button>
                      <button onClick={() => { const r = prompt("Rejection reason:"); if (r) reject.mutate({ id: i.id, reason: r }); }} title="Reject"
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
    </div>
  );
}
