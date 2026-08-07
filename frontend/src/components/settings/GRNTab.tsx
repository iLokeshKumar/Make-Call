"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

type GRN = {
  id: number;
  grn_number: string | null;
  po_id: number | null;
  status: string;
  has_discrepancy: boolean;
  discrepancy_notes: string | null;
  received_at: string;
};

type PurchaseKPIs = {
  grns: {
    total: number;
    discrepancy_count: number;
    discrepancy_rate_pct: number | null;
    total_units_received: number;
  };
};

const STATUS_COLORS: Record<string, string> = {
  received: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  verified: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  discrepancy: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
}

function ResolveDialog({ grn, onClose }: { grn: GRN; onClose: () => void }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");

  const resolve = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/purchase/grns/${grn.id}/resolve`, {
      resolved_by_user_id: 0,
      resolution_notes: notes,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-grns"] });
      qc.invalidateQueries({ queryKey: ["purchase-kpis"] });
      toast.success("Discrepancy resolved");
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-xl p-6 w-full max-w-md mx-4 space-y-4">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Resolve Discrepancy</h3>
        <p className="text-xs text-slate-500">GRN {grn.grn_number ?? `#${grn.id}`}</p>
        {grn.discrepancy_notes && (
          <div className="rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
            {grn.discrepancy_notes}
          </div>
        )}
        <div>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1 block">Resolution notes *</label>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            placeholder="Describe how the discrepancy was resolved…"
            className="w-full text-sm px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 resize-none"
          />
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">
            Cancel
          </button>
          <button
            onClick={() => resolve.mutate()}
            disabled={!notes.trim() || resolve.isPending}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
            {resolve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Resolve
          </button>
        </div>
      </div>
    </div>
  );
}

export default function GRNTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const [discrepancyOnly, setDiscrepancyOnly] = useState(false);
  const [resolving, setResolving] = useState<GRN | null>(null);

  const { data: grns = [], isLoading } = useQuery({
    queryKey: ["purchase-grns", discrepancyOnly],
    queryFn: () => {
      const url = discrepancyOnly
        ? `${CRM_BASE}/purchase/grns?has_discrepancy=true`
        : `${CRM_BASE}/purchase/grns`;
      return apiGet<{ grns: GRN[] }>(url).then(r => r.grns ?? []);
    },
  });

  const { data: kpis } = useQuery({
    queryKey: ["purchase-kpis"],
    queryFn: () => apiGet<PurchaseKPIs>(`${CRM_BASE}/purchase/kpis`),
  });

  const grnKpis = kpis?.grns;

  return (
    <div className="space-y-6 max-w-4xl">
      {resolving && <ResolveDialog grn={resolving} onClose={() => setResolving(null)} />}

      {/* KPI bar */}
      {grnKpis && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Total GRNs", value: grnKpis.total },
            {
              label: "Discrepancies",
              value: grnKpis.discrepancy_count,
              warn: grnKpis.discrepancy_count > 0,
            },
            {
              label: "Discrepancy Rate",
              value: grnKpis.discrepancy_rate_pct != null
                ? `${grnKpis.discrepancy_rate_pct}%`
                : "—",
              warn: (grnKpis.discrepancy_rate_pct ?? 0) > 5,
            },
          ].map(k => (
            <div key={k.label} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3">
              <p className="text-xs text-slate-500">{k.label}</p>
              <p className={`text-2xl font-bold mt-0.5 ${k.warn ? "text-rose-600 dark:text-rose-400" : "text-slate-900 dark:text-slate-100"}`}>
                {k.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Discrepancy alert */}
      {grnKpis && grnKpis.discrepancy_count > 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 px-4 py-3 text-rose-800 dark:text-rose-300 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {grnKpis.discrepancy_count} GRN{grnKpis.discrepancy_count > 1 ? "s" : ""} with unresolved discrepancies.
        </div>
      )}

      {/* Filter toggle */}
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={discrepancyOnly}
            onChange={e => setDiscrepancyOnly(e.target.checked)}
            className="rounded"
          />
          Show discrepancies only
        </label>
      </div>

      {/* GRN table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">GRN #</th>
              <th className="px-4 py-3 text-left">PO</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">Received</th>
              <th className="px-4 py-3 text-left">Discrepancy</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading ? (
              <tr><td colSpan={6} className="py-10 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
            ) : grns.length === 0 ? (
              <tr><td colSpan={6} className="py-10 text-center text-sm text-slate-400">
                {discrepancyOnly ? "No GRNs with discrepancies." : "No GRNs found."}
              </td></tr>
            ) : grns.map(g => (
              <tr key={g.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                  {g.grn_number ?? `#${g.id}`}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {g.po_id ? `PO #${g.po_id}` : "—"}
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${STATUS_COLORS[g.status] ?? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"}`}>
                    {g.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(g.received_at)}</td>
                <td className="px-4 py-3">
                  {g.has_discrepancy ? (
                    <span className="flex items-center gap-1 text-xs text-rose-600 dark:text-rose-400 font-medium">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {g.discrepancy_notes ? g.discrepancy_notes.slice(0, 40) + (g.discrepancy_notes.length > 40 ? "…" : "") : "Yes"}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  {g.has_discrepancy && g.status !== "verified" && (
                    <button
                      onClick={() => setResolving(g)}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 ml-auto">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Resolve
                    </button>
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
