"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, AlertTriangle, Flag, CheckCircle2 } from "lucide-react";
import { apiGet, apiPost, CRM_BASE } from "@/lib/api";
import { toast } from "sonner";

type PO = {
  id: number;
  po_number: string | null;
  status: string;
  total_value_inr: string;
  expected_delivery_date: string | null;
  sent_at: string | null;
  zoho_po_id: string | null;
  created_at: string;
};

type PurchaseKPIs = {
  purchase_orders: {
    total: number;
    overdue: number;
    total_value_ordered_inr: number;
    status_counts: Record<string, number>;
  };
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  sent: "Sent",
  acknowledged: "Acknowledged",
  in_transit: "In Transit",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  sent: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  acknowledged: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  in_transit: "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300",
  delivered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  cancelled: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
};

function fmt(amount: string | number) {
  return `₹${Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
}

export default function PurchaseOrdersTab({ sessionTimeout: _s }: { sessionTimeout?: () => void }) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [ackRef, setAckRef] = useState<Record<number, string>>({});
  const [ackOpen, setAckOpen] = useState<number | null>(null);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["purchase-orders", statusFilter],
    queryFn: () => {
      const url = statusFilter === "all"
        ? `${CRM_BASE}/purchase/orders`
        : `${CRM_BASE}/purchase/orders?status=${statusFilter}`;
      return apiGet<{ orders: PO[] }>(url).then(r => r.orders ?? []);
    },
  });

  const { data: kpis } = useQuery({
    queryKey: ["purchase-kpis"],
    queryFn: () => apiGet<PurchaseKPIs>(`${CRM_BASE}/purchase/kpis`),
  });

  const acknowledge = useMutation({
    mutationFn: ({ id, ref }: { id: number; ref?: string }) =>
      apiPost(`${CRM_BASE}/purchase/orders/${id}/acknowledge`, {
        acknowledged_by_user_id: 0,
        samsung_acknowledgement_ref: ref || undefined,
      }),
    onSuccess: (_r, { id }) => {
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["purchase-kpis"] });
      setAckOpen(null);
      setAckRef(prev => { const n = { ...prev }; delete n[id]; return n; });
      toast.success("PO acknowledged");
    },
  });

  const flagOverdue = useMutation({
    mutationFn: () => apiPost(`${CRM_BASE}/purchase/orders/flag-overdue`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      qc.invalidateQueries({ queryKey: ["purchase-kpis"] });
      toast.success("Overdue check queued");
    },
  });

  const poKpis = kpis?.purchase_orders;

  const STATUSES = ["all", "draft", "sent", "acknowledged", "in_transit", "delivered", "cancelled"];

  return (
    <div className="space-y-6 max-w-4xl">
      {/* KPI bar */}
      {poKpis && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Total POs", value: poKpis.total },
            { label: "Overdue", value: poKpis.overdue, warn: poKpis.overdue > 0 },
            { label: "Value Ordered", value: fmt(poKpis.total_value_ordered_inr) },
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

      {/* Overdue warning */}
      {poKpis && poKpis.overdue > 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-4 py-3 text-amber-800 dark:text-amber-300 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {poKpis.overdue} PO{poKpis.overdue > 1 ? "s" : ""} past expected delivery date. Run "Flag Overdue" to notify supplier.
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-1 flex-wrap">
          {STATUSES.map(s => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${statusFilter === s ? "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900" : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"}`}>
              {s === "all" ? "All" : STATUS_LABELS[s]}
              {s !== "all" && poKpis?.status_counts[s] ? ` (${poKpis.status_counts[s]})` : ""}
            </button>
          ))}
        </div>
        <button onClick={() => flagOverdue.mutate()} disabled={flagOverdue.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-50">
          {flagOverdue.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Flag className="h-3.5 w-3.5" />}
          Flag Overdue
        </button>
      </div>

      {/* PO table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">PO #</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-right">Value</th>
              <th className="px-4 py-3 text-left">Exp. Delivery</th>
              <th className="px-4 py-3 text-left">Sent</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {isLoading ? (
              <tr><td colSpan={6} className="py-10 text-center"><Loader2 className="h-5 w-5 animate-spin mx-auto text-slate-400" /></td></tr>
            ) : orders.length === 0 ? (
              <tr><td colSpan={6} className="py-10 text-center text-sm text-slate-400">No purchase orders found.</td></tr>
            ) : orders.map(po => (
              <tr key={po.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                  {po.po_number ?? `#${po.id}`}
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_COLORS[po.status] ?? STATUS_COLORS.draft}`}>
                    {STATUS_LABELS[po.status] ?? po.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-semibold text-slate-800 dark:text-slate-200">
                  {fmt(po.total_value_inr)}
                </td>
                <td className="px-4 py-3 text-slate-500 text-xs">{fmtDate(po.expected_delivery_date)}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{fmtDate(po.sent_at)}</td>
                <td className="px-4 py-3 text-right">
                  {po.status === "sent" && (
                    ackOpen === po.id ? (
                      <div className="flex items-center gap-1 justify-end">
                        <input
                          type="text"
                          placeholder="Samsung ref (optional)"
                          value={ackRef[po.id] ?? ""}
                          onChange={e => setAckRef(prev => ({ ...prev, [po.id]: e.target.value }))}
                          className="text-xs px-2 py-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 w-36"
                        />
                        <button
                          onClick={() => acknowledge.mutate({ id: po.id, ref: ackRef[po.id] })}
                          disabled={acknowledge.isPending}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
                          {acknowledge.isPending && acknowledge.variables?.id === po.id
                            ? <Loader2 className="h-3 w-3 animate-spin" />
                            : <CheckCircle2 className="h-3 w-3" />}
                          Confirm
                        </button>
                        <button onClick={() => setAckOpen(null)}
                          className="px-2 py-1 rounded text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700">
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => setAckOpen(po.id)}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/30 ml-auto">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Acknowledge
                      </button>
                    )
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
