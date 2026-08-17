"use client";

import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import UserChip from "@/components/UserChip";
import {
  CheckCircle,
  Loader2,
  Package,
  Plus,
  Truck,
  X,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type Order = {
   id: number;
   order_number: string;
   lead_id: number;
   status: string;
   total_amount?: string;
   currency: string;
   expected_delivery_at?: string;
   confirmed_at?: string;
   delivered_at?: string;
   cancelled_at?: string;
   notes?: string;
   created_at?: string;
};

type Lead = { id: number; name: string };

const STATUS_COLORS: Record<string, string> = {
  pending:    "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  confirmed:  "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  processing: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  shipped:    "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  delivered:  "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  closed:     "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  cancelled:  "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

const STATUS_TABS = ["All", "Pending", "Confirmed", "Processing", "Shipped", "Delivered", "Closed", "Cancelled"];
const ORDER_STATUSES = ["pending", "confirmed", "processing", "shipped", "delivered", "closed", "cancelled"];
const CURRENCIES = ["INR", "USD", "EUR"];

function fmtDate(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtAmount(amount?: string | number | null, currency?: string) {
   if (amount == null) return "—";
   const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount;
   return new Intl.NumberFormat("en-IN", {
     style: "currency",
     currency: currency || "INR",
     maximumFractionDigits: 2,
   }).format(numAmount);
 }

export default function OrdersPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  const [activeTab, setActiveTab] = useState("All");

  // Create panel
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [currency, setCurrency] = useState("INR");
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [deliveryCity, setDeliveryCity] = useState("");
  const [deliveryState, setDeliveryState] = useState("");
  const [deliveryPincode, setDeliveryPincode] = useState("");
  const [expectedDeliveryAt, setExpectedDeliveryAt] = useState("");
  const [createNotes, setCreateNotes] = useState("");

  // Status update
  const [statusLoading, setStatusLoading] = useState<Record<number, boolean>>({});
  const [statusNotes, setStatusNotes] = useState<Record<number, string>>({});

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const ordersQuery = useQuery<Order[]>({
    queryKey: ["orders"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/orders`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load orders");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["orders-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const orders: Order[] = ordersQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = ordersQuery.isLoading;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));

  const filteredLeads = leads.filter((l) =>
    l.name.toLowerCase().includes(leadSearch.toLowerCase())
  );

  const filteredOrders =
    activeTab === "All"
      ? orders
      : orders.filter((o) => o.status === activeTab.toLowerCase());

  // Stats
  const totalOrders = orders.length;
  const confirmedCount = orders.filter((o) => o.status === "confirmed").length;
  const inProgressCount = orders.filter((o) => o.status === "processing" || o.status === "shipped").length;
  const deliveredCount = orders.filter((o) => o.status === "delivered").length;

  function resetCreateForm() {
    setSelectedLeadId(null);
    setLeadSearch("");
    setCurrency("INR");
    setDeliveryAddress("");
    setDeliveryCity("");
    setDeliveryState("");
    setDeliveryPincode("");
    setExpectedDeliveryAt("");
    setCreateNotes("");
  }

  async function handleCreate() {
    if (!selectedLeadId) { showToast("Select a lead", true); return; }
    setCreateSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lead_id: selectedLeadId,
          currency,
          delivery_address: deliveryAddress.trim() || null,
          delivery_city: deliveryCity.trim() || null,
          delivery_state: deliveryState.trim() || null,
          delivery_pincode: deliveryPincode.trim() || null,
          expected_delivery_at: expectedDeliveryAt || null,
          notes: createNotes.trim() || null,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to create order");
      }
      showToast("Order created successfully");
      setCreating(false);
      resetCreateForm();
      void qc.invalidateQueries({ queryKey: ["orders"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create order", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleStatusChange(id: number, newStatus: string) {
    setStatusLoading((prev) => ({ ...prev, [id]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/crm/orders/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus, notes: statusNotes[id] ?? null }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to update status");
      }
      showToast(`Order status updated to ${newStatus}`);
      void qc.invalidateQueries({ queryKey: ["orders"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Status update failed", true);
    } finally {
      setStatusLoading((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function handleCancel(id: number) {
    if (!window.confirm("Cancel this order?")) return;
    await handleStatusChange(id, "cancelled");
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            Sales
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Orders</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Track and manage customer orders
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { setCreating((v) => !v); if (creating) resetCreateForm(); }}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
          >
            <Plus className="h-4 w-4" /> New Order
          </button>
          <UserChip />
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm transition-all ${
            toastError
              ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
              : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
          }`}
        >
          {toast}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Total Orders",  value: totalOrders,    icon: Package,      color: "text-violet-600 dark:text-violet-400",  bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Confirmed",     value: confirmedCount, icon: CheckCircle,  color: "text-blue-600 dark:text-blue-400",      bg: "bg-blue-100 dark:bg-blue-500/10" },
          { label: "In Progress",   value: inProgressCount,icon: Truck,        color: "text-indigo-600 dark:text-indigo-400",  bg: "bg-indigo-100 dark:bg-indigo-500/10" },
          { label: "Delivered",     value: deliveredCount, icon: CheckCircle,  color: "text-emerald-600 dark:text-emerald-400",bg: "bg-emerald-100 dark:bg-emerald-500/10" },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex items-center gap-4">
            <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${bg}`}>
              <Icon className={`h-5 w-5 ${color}`} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Create panel */}
      {creating && (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Order</h2>
            <button
              onClick={() => { setCreating(false); resetCreateForm(); }}
              className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-white/10"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Lead selector */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Lead *</label>
              <input
                value={leadSearch}
                onChange={(e) => { setLeadSearch(e.target.value); setSelectedLeadId(null); }}
                placeholder="Search lead name…"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
              {leadSearch && !selectedLeadId && filteredLeads.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900 max-h-40 overflow-y-auto z-10 relative">
                  {filteredLeads.slice(0, 10).map((l) => (
                    <button
                      key={l.id}
                      onClick={() => { setSelectedLeadId(l.id); setLeadSearch(l.name); }}
                      className="w-full px-3 py-2 text-left text-sm hover:bg-violet-50 dark:hover:bg-violet-500/10 text-slate-800 dark:text-slate-100"
                    >
                      {l.name}
                    </button>
                  ))}
                </div>
              )}
              {selectedLeadId && (
                <p className="text-xs text-emerald-600 dark:text-emerald-400">Lead selected</p>
              )}
            </div>

            {/* Currency */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Currency</label>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              >
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {/* Expected Delivery */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Expected Delivery Date</label>
              <input
                type="date"
                value={expectedDeliveryAt}
                onChange={(e) => setExpectedDeliveryAt(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Delivery Address */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Delivery Address</label>
              <input
                value={deliveryAddress}
                onChange={(e) => setDeliveryAddress(e.target.value)}
                placeholder="Street address"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Delivery City */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">City</label>
              <input
                value={deliveryCity}
                onChange={(e) => setDeliveryCity(e.target.value)}
                placeholder="Mumbai"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Delivery State */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">State</label>
              <input
                value={deliveryState}
                onChange={(e) => setDeliveryState(e.target.value)}
                placeholder="Maharashtra"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Pincode */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Pincode</label>
              <input
                value={deliveryPincode}
                onChange={(e) => setDeliveryPincode(e.target.value)}
                placeholder="400001"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Notes</label>
            <textarea
              value={createNotes}
              onChange={(e) => setCreateNotes(e.target.value)}
              rows={2}
              placeholder="Optional notes…"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleCreate}
              disabled={createSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Order
            </button>
            <button
              onClick={() => { setCreating(false); resetCreateForm(); }}
              className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50 w-fit">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-all ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading orders…
        </div>
      ) : filteredOrders.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {activeTab === "All" ? "No orders yet. Create your first order above." : `No ${activeTab.toLowerCase()} orders.`}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Order #", "Lead", "Status", "Total Amount", "Expected Delivery", "Created", "Actions"].map((col) => (
                    <th
                      key={col}
                      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {filteredOrders.map((order) => (
                  <tr
                    key={order.id}
                    className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                      {order.order_number}
                    </td>
                    <td className="px-4 py-3 text-slate-800 dark:text-slate-100">
                      {leadMap[order.lead_id] ?? `Lead #${order.lead_id}`}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
                          STATUS_COLORS[order.status] ?? STATUS_COLORS.pending
                        }`}
                      >
                        {order.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                      {fmtAmount(order.total_amount, order.currency)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                      {fmtDate(order.expected_delivery_at)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                      {fmtDate(order.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {/* Status dropdown */}
                        <select
                          value={order.status}
                          disabled={statusLoading[order.id]}
                          onChange={(e) => handleStatusChange(order.id, e.target.value)}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white disabled:opacity-50"
                        >
                          {ORDER_STATUSES.map((s) => (
                            <option key={s} value={s} className="capitalize">{s}</option>
                          ))}
                        </select>
                        {statusLoading[order.id] && (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                        )}
                        {/* Cancel button */}
                        {order.status !== "cancelled" && (
                          <button
                            title="Cancel order"
                            onClick={() => handleCancel(order.id)}
                            disabled={statusLoading[order.id]}
                            className="rounded-lg p-1.5 text-red-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-500/10"
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
