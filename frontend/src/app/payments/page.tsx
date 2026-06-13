"use client";

import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CreditCard,
  DollarSign,
  Loader2,
  Plus,
  RefreshCw,
  Search,
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

type Payment = {
   id: number;
   invoice_id: number;
   lead_id: number;
   amount?: string;
   currency: string;
   status: string;
   payment_method: string;
   reference_number?: string;
   gateway?: string;
   captured_at?: string;
   notes?: string;
   created_at?: string;
};

type Invoice = {
   id: number;
   invoice_number: string;
   total_amount?: string;
   amount_due?: string;
   lead_id?: number;
};

type Lead = { id: number; name: string };

const STATUS_COLORS: Record<string, string> = {
  pending:  "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  captured: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  failed:   "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  refunded: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

const PAYMENT_METHODS = ["bank_transfer", "upi", "cheque", "cash", "card", "online"];
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

export default function PaymentsPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  const [search, setSearch] = useState("");

  // Record payment panel
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [paymentMethod, setPaymentMethod] = useState("bank_transfer");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [gateway, setGateway] = useState("");
  const [createNotes, setCreateNotes] = useState("");

  // Reconcile loading per invoice
  const [reconcileLoading, setReconcileLoading] = useState<Record<number, boolean>>({});

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const paymentsQuery = useQuery<Payment[]>({
    queryKey: ["payments"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/payments`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load payments");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const invoicesQuery = useQuery<Invoice[]>({
    queryKey: ["payments-invoices"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/invoices`);
      if (!res.ok) return [];
      const d = await res.json();
      return Array.isArray(d) ? d : d.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["payments-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const payments: Payment[] = paymentsQuery.data ?? [];
  const invoices: Invoice[] = invoicesQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = paymentsQuery.isLoading;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));
  const invoiceMap = Object.fromEntries(invoices.map((inv) => [inv.id, inv]));

  const filteredLeads = leads.filter((l) =>
    l.name.toLowerCase().includes(leadSearch.toLowerCase())
  );

  // Invoices filtered by selected lead
  const leadInvoices = selectedLeadId
    ? invoices.filter((inv) => inv.lead_id === selectedLeadId)
    : invoices;

  // Search filter
  const filteredPayments = payments.filter((p) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      (p.reference_number ?? "").toLowerCase().includes(q) ||
      (p.gateway ?? "").toLowerCase().includes(q)
    );
  });

  // Stats
  const totalPayments = payments.length;
  const totalCaptured = payments
    .filter((p) => p.status === "captured")
    .reduce((sum, p) => {
      const val = p.amount ? parseFloat(p.amount) : 0;
      return sum + (isNaN(val) ? 0 : val);
    }, 0);
  const pendingCount = payments.filter((p) => p.status === "pending").length;

  function resetCreateForm() {
    setLeadSearch("");
    setSelectedLeadId(null);
    setSelectedInvoiceId(null);
    setAmount("");
    setCurrency("INR");
    setPaymentMethod("bank_transfer");
    setReferenceNumber("");
    setGateway("");
    setCreateNotes("");
  }

  async function handleCreate() {
    if (!selectedLeadId) { showToast("Select a lead", true); return; }
    if (!selectedInvoiceId) { showToast("Select an invoice", true); return; }
    if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) {
      showToast("Enter a valid amount", true);
      return;
    }
    setCreateSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/payments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invoice_id: selectedInvoiceId,
          lead_id: selectedLeadId,
          amount: Number(amount),
          currency,
          payment_method: paymentMethod,
          reference_number: referenceNumber.trim() || null,
          gateway: gateway.trim() || null,
          notes: createNotes.trim() || null,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to record payment");
      }
      showToast("Payment recorded successfully");
      setCreating(false);
      resetCreateForm();
      void qc.invalidateQueries({ queryKey: ["payments"] });
      void qc.invalidateQueries({ queryKey: ["payments-invoices"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to record payment", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleReconcile(invoiceId: number) {
    setReconcileLoading((prev) => ({ ...prev, [invoiceId]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/crm/payments/reconcile/${invoiceId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Reconciliation failed");
      }
      showToast(`Invoice #${invoiceId} reconciled successfully`);
      void qc.invalidateQueries({ queryKey: ["payments"] });
      void qc.invalidateQueries({ queryKey: ["payments-invoices"] });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Reconciliation failed", true);
    } finally {
      setReconcileLoading((prev) => ({ ...prev, [invoiceId]: false }));
    }
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
            <span className="gradient-text">Payments</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Record and track customer payments
          </p>
        </div>
        <button
          onClick={() => { setCreating((v) => !v); if (creating) resetCreateForm(); }}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
        >
          <Plus className="h-4 w-4" /> Record Payment
        </button>
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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: "Total Payments",        value: String(totalPayments),               icon: CreditCard,  color: "text-violet-600 dark:text-violet-400",  bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Total Amount Captured", value: fmtAmount(totalCaptured, "INR"),     icon: DollarSign,  color: "text-emerald-600 dark:text-emerald-400",bg: "bg-emerald-100 dark:bg-emerald-500/10" },
          { label: "Pending",               value: String(pendingCount),                icon: RefreshCw,   color: "text-amber-600 dark:text-amber-400",    bg: "bg-amber-100 dark:bg-amber-500/10" },
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

      {/* Record Payment panel */}
      {creating && (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Record Payment</h2>
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
                onChange={(e) => {
                  setLeadSearch(e.target.value);
                  setSelectedLeadId(null);
                  setSelectedInvoiceId(null);
                }}
                placeholder="Search lead name…"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
              {leadSearch && !selectedLeadId && filteredLeads.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900 max-h-40 overflow-y-auto z-10 relative">
                  {filteredLeads.slice(0, 10).map((l) => (
                    <button
                      key={l.id}
                      onClick={() => {
                        setSelectedLeadId(l.id);
                        setLeadSearch(l.name);
                        setSelectedInvoiceId(null);
                      }}
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

            {/* Invoice selector — filtered by lead */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Invoice *</label>
              <select
                value={selectedInvoiceId ?? ""}
                onChange={(e) => setSelectedInvoiceId(e.target.value ? Number(e.target.value) : null)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              >
                <option value="">Select invoice…</option>
                {leadInvoices.map((inv) => (
                  <option key={inv.id} value={inv.id}>
                    {inv.invoice_number}
                    {inv.amount_due != null ? ` — Due: ${fmtAmount(inv.amount_due, "INR")}` : ""}
                  </option>
                ))}
              </select>
            </div>

            {/* Amount */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Amount *</label>
              <input
                type="number"
                min={0}
                step={0.01}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
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

            {/* Payment method */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Payment Method *</label>
              <select
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              >
                {PAYMENT_METHODS.map((m) => (
                  <option key={m} value={m}>{m.replace("_", " ")}</option>
                ))}
              </select>
            </div>

            {/* Reference number */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Reference Number</label>
              <input
                value={referenceNumber}
                onChange={(e) => setReferenceNumber(e.target.value)}
                placeholder="TXN123456"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
              />
            </div>

            {/* Gateway */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Gateway (optional)</label>
              <input
                value={gateway}
                onChange={(e) => setGateway(e.target.value)}
                placeholder="e.g. Razorpay"
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
              Record Payment
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

      {/* Search bar */}
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by reference or gateway…"
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading payments…
        </div>
      ) : filteredPayments.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {search ? `No payments matching "${search}".` : "No payments yet. Record your first payment above."}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["ID", "Invoice #", "Lead", "Amount", "Method", "Status", "Reference", "Gateway", "Captured At", "Actions"].map((col) => (
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
                {filteredPayments.map((payment) => {
                  const inv = invoiceMap[payment.invoice_id];
                  return (
                    <tr
                      key={payment.id}
                      className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">
                        #{payment.id}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                        {inv?.invoice_number ?? `Inv #${payment.invoice_id}`}
                      </td>
                      <td className="px-4 py-3 text-slate-800 dark:text-slate-100">
                        {leadMap[payment.lead_id] ?? `Lead #${payment.lead_id}`}
                      </td>
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                        {fmtAmount(payment.amount, payment.currency)}
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-300 capitalize">
                        {payment.payment_method.replace("_", " ")}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
                            STATUS_COLORS[payment.status] ?? STATUS_COLORS.pending
                          }`}
                        >
                          {payment.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400 font-mono text-xs">
                        {payment.reference_number ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {payment.gateway ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {fmtDate(payment.captured_at)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          title="Reconcile invoice"
                          onClick={() => handleReconcile(payment.invoice_id)}
                          disabled={reconcileLoading[payment.invoice_id]}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:border-violet-400 hover:text-violet-600 disabled:opacity-50 dark:border-white/10 dark:text-slate-300 dark:hover:border-violet-500/40 dark:hover:text-violet-300 transition-colors"
                        >
                          {reconcileLoading[payment.invoice_id] ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3 w-3" />
                          )}
                          Reconcile
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
