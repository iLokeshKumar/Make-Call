"use client";

import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle,
  FileText,
  Loader2,
  Plus,
  Send,
  X,
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

type Invoice = {
   id: number;
   invoice_number: string;
   order_id?: number;
   lead_id: number;
   status: string;
   total_amount?: string;
   amount_paid?: string;
   amount_due?: string;
   currency: string;
   due_date?: string;
   sent_at?: string;
   paid_at?: string;
   requires_approval: boolean;
   notes?: string;
   created_at?: string;
};

type Lead = { id: number; name: string };

const STATUS_COLORS: Record<string, string> = {
  draft:           "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  sent:            "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  partially_paid:  "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  paid:            "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  overdue:         "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  cancelled:       "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  written_off:     "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

const STATUS_TABS = ["All", "Draft", "Sent", "Partially Paid", "Paid", "Overdue"];
const CURRENCIES = ["INR", "USD", "EUR"];

function tabToStatus(tab: string): string {
  if (tab === "Partially Paid") return "partially_paid";
  return tab.toLowerCase();
}

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

export default function InvoicesPage() {
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
  const [orderId, setOrderId] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [dueDate, setDueDate] = useState("");
  const [billingAddress, setBillingAddress] = useState("");
  const [gstNumber, setGstNumber] = useState("");
  const [createNotes, setCreateNotes] = useState("");
  const [requiresApproval, setRequiresApproval] = useState(false);

  // Send modal
  const [sendingInvoiceId, setSendingInvoiceId] = useState<number | null>(null);
  const [sendVia, setSendVia] = useState<string[]>([]);
  const [sendSaving, setSendSaving] = useState(false);

  // From Order
  const [fromOrderId, setFromOrderId] = useState("");
  const [fromOrderSaving, setFromOrderSaving] = useState(false);
  const [showFromOrder, setShowFromOrder] = useState(false);

  // Action loading
  const [actionLoading, setActionLoading] = useState<Record<number, boolean>>({});

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const invoicesQuery = useQuery<Invoice[]>({
    queryKey: ["invoices"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/invoices`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load invoices");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["invoices-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const invoices: Invoice[] = invoicesQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = invoicesQuery.isLoading;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));

  const filteredLeads = leads.filter((l) =>
    l.name.toLowerCase().includes(leadSearch.toLowerCase())
  );

  const filteredInvoices =
    activeTab === "All"
      ? invoices
      : invoices.filter((inv) => inv.status === tabToStatus(activeTab));

  // Stats
  const totalInvoices = invoices.length;
  const now = new Date();
  const currentMonth = now.getMonth();
  const currentYear = now.getFullYear();
  const totalOutstanding = invoices
    .filter((inv) => inv.status !== "paid" && inv.status !== "written_off" && inv.status !== "cancelled")
    .reduce((sum, inv) => {
      const val = inv.amount_due ? parseFloat(inv.amount_due) : 0;
      return sum + (isNaN(val) ? 0 : val);
    }, 0);
  const paidThisMonth = invoices
    .filter((inv) => {
      if (!inv.paid_at) return false;
      const d = new Date(inv.paid_at);
      return d.getMonth() === currentMonth && d.getFullYear() === currentYear;
    })
    .reduce((sum, inv) => {
      const val = inv.total_amount ? parseFloat(inv.total_amount) : 0;
      return sum + (isNaN(val) ? 0 : val);
    }, 0);
  const overdueCount = invoices.filter((inv) => inv.status === "overdue").length;

  function resetCreateForm() {
    setSelectedLeadId(null);
    setLeadSearch("");
    setOrderId("");
    setCurrency("INR");
    setDueDate("");
    setBillingAddress("");
    setGstNumber("");
    setCreateNotes("");
    setRequiresApproval(false);
  }

  async function handleCreate() {
    if (!selectedLeadId) { showToast("Select a lead", true); return; }
    setCreateSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/invoices`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lead_id: selectedLeadId,
          order_id: orderId ? Number(orderId) : null,
          currency,
          due_date: dueDate || null,
          billing_address: billingAddress.trim() || null,
          gst_number: gstNumber.trim() || null,
          notes: createNotes.trim() || null,
          requires_approval: requiresApproval,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to create invoice");
      }
      showToast("Invoice created successfully");
      setCreating(false);
      resetCreateForm();
      void qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create invoice", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleSend(id: number) {
    if (sendVia.length === 0) { showToast("Select at least one channel", true); return; }
    setSendSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/invoices/${id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ send_via: sendVia }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to send invoice");
      }
      showToast("Invoice sent successfully");
      setSendingInvoiceId(null);
      setSendVia([]);
      void qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Send failed", true);
    } finally {
      setSendSaving(false);
    }
  }

  async function handleFromOrder() {
    if (!fromOrderId.trim()) { showToast("Enter an order ID", true); return; }
    setFromOrderSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/invoices/from-order/${fromOrderId.trim()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to create invoice from order");
      }
      showToast("Invoice created from order");
      setFromOrderId("");
      setShowFromOrder(false);
      void qc.invalidateQueries({ queryKey: ["invoices"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed", true);
    } finally {
      setFromOrderSaving(false);
    }
  }

  function toggleSendChannel(ch: string) {
    setSendVia((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]
    );
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            Finance
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Invoices</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Manage and track customer invoices
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => { setShowFromOrder((v) => !v); setCreating(false); }}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-violet-300 hover:text-violet-700 dark:border-white/10 dark:text-slate-200 dark:hover:border-violet-500/40 dark:hover:text-violet-300"
          >
            <FileText className="h-4 w-4" /> From Order
          </button>
          <button
            onClick={() => { setCreating((v) => !v); setShowFromOrder(false); if (creating) resetCreateForm(); }}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
          >
            <Plus className="h-4 w-4" /> New Invoice
          </button>
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
          { label: "Total Invoices",    value: totalInvoices,                     icon: FileText,    color: "text-violet-600 dark:text-violet-400",  bg: "bg-violet-100 dark:bg-violet-500/10",  isAmount: false },
          { label: "Total Outstanding", value: fmtAmount(totalOutstanding, "INR"), icon: AlertCircle, color: "text-amber-600 dark:text-amber-400",    bg: "bg-amber-100 dark:bg-amber-500/10",    isAmount: true },
          { label: "Paid This Month",   value: fmtAmount(paidThisMonth, "INR"),    icon: CheckCircle, color: "text-emerald-600 dark:text-emerald-400",bg: "bg-emerald-100 dark:bg-emerald-500/10",isAmount: true },
          { label: "Overdue",           value: overdueCount,                      icon: AlertCircle, color: "text-red-600 dark:text-red-400",        bg: "bg-red-100 dark:bg-red-500/10",        isAmount: false },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex items-center gap-4">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${bg}`}>
              <Icon className={`h-5 w-5 ${color}`} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-bold text-slate-900 dark:text-white truncate">{value}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* From Order panel */}
      {showFromOrder && (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Create Invoice from Order</h2>
            <button
              onClick={() => setShowFromOrder(false)}
              className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-white/10"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-end gap-3">
            <div className="space-y-1.5 flex-1 max-w-xs">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Order ID</label>
              <input
                type="number"
                value={fromOrderId}
                onChange={(e) => setFromOrderId(e.target.value)}
                placeholder="e.g. 42"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>
            <button
              onClick={handleFromOrder}
              disabled={fromOrderSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {fromOrderSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              Generate
            </button>
          </div>
        </div>
      )}

      {/* Create panel */}
      {creating && (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Invoice</h2>
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

            {/* Order ID */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Order ID (optional)</label>
              <input
                type="number"
                value={orderId}
                onChange={(e) => setOrderId(e.target.value)}
                placeholder="e.g. 42"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
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

            {/* Due Date */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Due Date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Billing Address */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Billing Address</label>
              <input
                value={billingAddress}
                onChange={(e) => setBillingAddress(e.target.value)}
                placeholder="Full billing address"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* GST Number */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">GST Number</label>
              <input
                value={gstNumber}
                onChange={(e) => setGstNumber(e.target.value)}
                placeholder="e.g. 27AAACR5055K1Z5"
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

          {/* Requires approval toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="requires_approval"
              checked={requiresApproval}
              onChange={(e) => setRequiresApproval(e.target.checked)}
              className="h-4 w-4 rounded accent-violet-600"
            />
            <label
              htmlFor="requires_approval"
              className="text-sm font-medium text-slate-600 dark:text-slate-300 cursor-pointer"
            >
              Requires approval before sending
            </label>
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleCreate}
              disabled={createSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Invoice
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
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading invoices…
        </div>
      ) : filteredInvoices.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {activeTab === "All" ? "No invoices yet. Create your first invoice above." : `No ${activeTab.toLowerCase()} invoices.`}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Invoice #", "Lead", "Status", "Total", "Paid", "Due", "Due Date", "Sent At", "Actions"].map((col) => (
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
                {filteredInvoices.map((invoice) => (
                  <React.Fragment key={invoice.id}>
                    <tr className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                        {invoice.invoice_number}
                      </td>
                      <td className="px-4 py-3 text-slate-800 dark:text-slate-100">
                        {leadMap[invoice.lead_id] ?? `Lead #${invoice.lead_id}`}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            STATUS_COLORS[invoice.status] ?? STATUS_COLORS.draft
                          }`}
                        >
                          {invoice.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                        {fmtAmount(invoice.total_amount, invoice.currency)}
                      </td>
                      <td className="px-4 py-3 text-emerald-600 dark:text-emerald-400">
                        {fmtAmount(invoice.amount_paid, invoice.currency)}
                      </td>
                      <td className="px-4 py-3 text-red-600 dark:text-red-400">
                        {fmtAmount(invoice.amount_due, invoice.currency)}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {fmtDate(invoice.due_date)}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {fmtDate(invoice.sent_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {/* Send button — on draft or sent */}
                          {(invoice.status === "draft" || invoice.status === "sent") && (
                            <button
                              title="Send invoice"
                              onClick={() => {
                                setSendingInvoiceId(sendingInvoiceId === invoice.id ? null : invoice.id);
                                setSendVia([]);
                              }}
                              disabled={actionLoading[invoice.id]}
                              className="rounded-lg p-1.5 text-blue-500 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:hover:bg-blue-500/10 dark:hover:text-blue-300"
                            >
                              <Send className="h-4 w-4" />
                            </button>
                          )}
                          {actionLoading[invoice.id] && (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Inline send modal */}
                    {sendingInvoiceId === invoice.id && (
                      <tr>
                        <td colSpan={9} className="bg-blue-50/60 dark:bg-blue-500/5 px-4 py-4">
                          <div className="space-y-3 max-w-sm">
                            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                              Send {invoice.invoice_number}
                            </p>
                            <div className="flex items-center gap-4">
                              {["email", "whatsapp"].map((ch) => (
                                <label key={ch} className="flex items-center gap-2 cursor-pointer">
                                  <input
                                    type="checkbox"
                                    checked={sendVia.includes(ch)}
                                    onChange={() => toggleSendChannel(ch)}
                                    className="h-4 w-4 rounded border-slate-300 text-violet-600"
                                  />
                                  <span className="text-sm capitalize text-slate-700 dark:text-slate-200">{ch}</span>
                                </label>
                              ))}
                            </div>
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleSend(invoice.id)}
                                disabled={sendSaving || sendVia.length === 0}
                                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
                              >
                                {sendSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                Send
                              </button>
                              <button
                                onClick={() => setSendingInvoiceId(null)}
                                className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
