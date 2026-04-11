"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  CheckCircle,
  FileDown,
  FileText,
  Loader2,
  Plus,
  Send,
  Trash2,
  XCircle,
  DollarSign,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Quote = {
  id: number;
  quote_number: string;
  lead_id: number;
  status: string;
  total_amount?: number | null;
  currency: string;
  valid_until?: string | null;
  notes?: string | null;
  sent_at?: string | null;
  opened_at?: string | null;
  accepted_at?: string | null;
  rejected_at?: string | null;
  created_at?: string;
};

type QuoteItem = {
  product_id?: number | null;
  product_name_snapshot: string;
  sku_snapshot?: string;
  quantity: number;
  unit_price: number;
  discount_percent?: number;
};

type Lead = { id: number; name: string };
type Product = { id: number; name: string; sku: string; base_price?: number; currency?: string };

const CURRENCIES = ["INR", "USD", "EUR"];

function fmtDate(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtAmount(amount?: number | null, currency?: string) {
  if (amount == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency || "INR",
    maximumFractionDigits: 2,
  }).format(amount);
}

const STATUS_COLORS: Record<string, string> = {
  draft:       "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  pending:     "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  sent:        "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  accepted:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  rejected:    "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  negotiation: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  expired:     "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500",
};

const STATUS_TABS = ["All", "Draft", "Sent", "Accepted", "Rejected", "Negotiation"];

const emptyItem = (): QuoteItem => ({
  product_name_snapshot: "",
  sku_snapshot: "",
  quantity: 1,
  unit_price: 0,
  discount_percent: 0,
});

export default function QuotesPage() {
  const { token, sessionTimeout } = useAuth();

  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);

  // filter
  const [activeTab, setActiveTab] = useState("All");

  // create panel
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [currency, setCurrency] = useState("INR");
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<QuoteItem[]>([emptyItem()]);

  // send panel
  const [sendingQuoteId, setSendingQuoteId] = useState<number | null>(null);
  const [sendChannels, setSendChannels] = useState<string[]>([]);
  const [sendSubject, setSendSubject] = useState("");
  const [sendMessage, setSendMessage] = useState("");
  const [sendSaving, setSendSaving] = useState(false);

  // action loading
  const [actionLoading, setActionLoading] = useState<Record<number, Record<string, boolean>>>({});
  const [exportLoading, setExportLoading] = useState(false);

  const authHeaders = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const fetchQuotes = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/quotes`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load quotes");
      const data = await res.json();
      setQuotes(Array.isArray(data) ? data : data.items ?? []);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to load quotes", true);
    } finally {
      setLoading(false);
    }
  }, [token, sessionTimeout]);

  const fetchLeads = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/crm/leads?page=1&limit=200`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const d = await res.json();
        setLeads(d.items ?? d ?? []);
      }
    } catch {
      
    }
  }, [token]);

  const fetchProducts = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/crm/products`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setProducts(await res.json());
    } catch {
      
    }
  }, [token]);

  useEffect(() => {
    fetchQuotes();
    fetchLeads();
    fetchProducts();
  }, [fetchQuotes, fetchLeads, fetchProducts]);

  // Derived stats
  const totalQuotes = quotes.length;
  const acceptedCount = quotes.filter((q) => q.status === "accepted").length;
  const pendingCount = quotes.filter((q) => q.status === "sent" || q.status === "draft").length;
  const rejectedCount = quotes.filter((q) => q.status === "rejected").length;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));

  const filteredQuotes =
    activeTab === "All" ? quotes : quotes.filter((q) => q.status === activeTab.toLowerCase());

  const filteredLeads = leads.filter((l) =>
    l.name.toLowerCase().includes(leadSearch.toLowerCase())
  );

  // Line item helpers
  function lineTotal(item: QuoteItem) {
    const gross = item.quantity * item.unit_price;
    const disc = ((item.discount_percent ?? 0) / 100) * gross;
    return gross - disc;
  }

  const grandTotal = items.reduce((sum, it) => sum + lineTotal(it), 0);

  function updateItem(idx: number, patch: Partial<QuoteItem>) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  function selectProduct(idx: number, productId: number) {
    const p = products.find((pr) => pr.id === productId);
    if (!p) return;
    updateItem(idx, {
      product_id: p.id,
      product_name_snapshot: p.name,
      sku_snapshot: p.sku,
      unit_price: p.base_price ?? 0,
    });
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleCreate() {
    if (!selectedLeadId) { showToast("Select a lead", true); return; }
    if (items.length === 0 || items.some((it) => !it.product_name_snapshot.trim())) {
      showToast("All line items need a product name", true);
      return;
    }
    setCreateSaving(true);
    try {
      const res = await fetch(`${API_BASE}/quotes`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({
          lead_id: selectedLeadId,
          currency,
          valid_until: validUntil || null,
          notes: notes.trim() || null,
          items: items.map((it) => ({
            product_id: it.product_id ?? null,
            product_name_snapshot: it.product_name_snapshot.trim(),
            sku_snapshot: it.sku_snapshot?.trim() || null,
            quantity: it.quantity,
            unit_price: it.unit_price,
            discount_percent: it.discount_percent ?? 0,
          })),
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to create quote");
      }
      showToast("Quote created successfully");
      setCreating(false);
      setSelectedLeadId(null);
      setLeadSearch("");
      setCurrency("INR");
      setValidUntil("");
      setNotes("");
      setItems([emptyItem()]);
      fetchQuotes();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create quote", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleGeneratePDF(id: number) {
    setActionLoading((a) => ({ ...a, [id]: { ...a[id], pdf: true } }));
    try {
      const res = await fetch(`${API_BASE}/quotes/${id}/generate-pdf`, {
        method: "POST",
        headers: authHeaders,
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to generate PDF");
      showToast("PDF generated");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "PDF generation failed", true);
    } finally {
      setActionLoading((a) => ({ ...a, [id]: { ...a[id], pdf: false } }));
    }
  }

  async function handleSend(id: number) {
    if (sendChannels.length === 0) { showToast("Select at least one channel", true); return; }
    setSendSaving(true);
    try {
      const res = await fetch(`${API_BASE}/quotes/${id}/send`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({
          channels: sendChannels,
          subject: sendSubject.trim() || null,
          message: sendMessage.trim() || null,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to send quote");
      }
      showToast("Quote sent successfully");
      setSendingQuoteId(null);
      setSendChannels([]);
      setSendSubject("");
      setSendMessage("");
      fetchQuotes();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Send failed", true);
    } finally {
      setSendSaving(false);
    }
  }

  async function handleExportQuoteCSV() {
    if (!token) return;
    if (quotes.length === 0) { showToast("No quotes available to export", true); return; }
    setExportLoading(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/quote/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `quotes_export_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("Quotes CSV downloaded");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Export failed", true);
    } finally {
      setExportLoading(false);
    }
  }

  async function handleStatusChange(id: number, action: "accept" | "reject") {
    setActionLoading((a) => ({ ...a, [id]: { ...a[id], [action]: true } }));
    try {
      const res = await fetch(`${API_BASE}/quotes/${id}/${action}`, {
        method: "POST",
        headers: authHeaders,
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Failed to ${action} quote`);
      showToast(`Quote ${action}ed`);
      fetchQuotes();
    } catch (e) {
      showToast(e instanceof Error ? e.message : `Action failed`, true);
    } finally {
      setActionLoading((a) => ({ ...a, [id]: { ...a[id], [action]: false } }));
    }
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
            <span className="gradient-text">Quotes</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Manage and track sales proposals
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExportQuoteCSV}
            disabled={exportLoading}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-violet-300 hover:text-violet-700 disabled:opacity-50 dark:border-white/10 dark:text-slate-200 dark:hover:border-violet-500/40 dark:hover:text-violet-300"
          >
            {exportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
            Export CSV
          </button>
          <button
            onClick={() => setCreating((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
          >
            <Plus className="h-4 w-4" /> New Quote
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
          { label: "Total Quotes", value: totalQuotes, icon: FileText, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Accepted", value: acceptedCount, icon: CheckCircle, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
          { label: "Pending", value: pendingCount, icon: DollarSign, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-100 dark:bg-blue-500/10" },
          { label: "Rejected", value: rejectedCount, icon: XCircle, color: "text-red-600 dark:text-red-400", bg: "bg-red-100 dark:bg-red-500/10" },
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
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Quote</h2>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Lead dropdown */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Lead *</label>
              <input
                value={leadSearch}
                onChange={(e) => { setLeadSearch(e.target.value); setSelectedLeadId(null); }}
                placeholder="Search lead name…"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
              {leadSearch && !selectedLeadId && filteredLeads.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900 max-h-40 overflow-y-auto">
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
                <p className="text-xs text-emerald-600 dark:text-emerald-400">Lead selected: ID {selectedLeadId}</p>
              )}
            </div>

            {/* Currency */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Currency</label>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              >
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {/* Valid Until */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Valid Until</label>
              <input
                type="date"
                value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Optional notes…"
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
          </div>

          {/* Line items */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Line Items</h3>
              <button
                onClick={() => setItems((prev) => [...prev, emptyItem()])}
                className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 hover:border-violet-400 hover:text-violet-600 dark:border-white/10"
              >
                <Plus className="h-3 w-3" /> Add item
              </button>
            </div>

            {/* Header row */}
            <div className="grid grid-cols-12 gap-2 text-xs font-medium text-slate-400 px-1">
              <div className="col-span-4">Product</div>
              <div className="col-span-2">SKU</div>
              <div className="col-span-1">Qty</div>
              <div className="col-span-2">Unit Price</div>
              <div className="col-span-2">Disc %</div>
              <div className="col-span-1"></div>
            </div>

            {items.map((item, idx) => (
              <div key={idx} className="grid grid-cols-12 gap-2 items-center">
                {/* Product name / dropdown */}
                <div className="col-span-4 relative">
                  {products.length > 0 ? (
                    <div className="space-y-1">
                      <select
                        value={item.product_id ?? ""}
                        onChange={(e) => {
                          const val = e.target.value;
                          if (val === "") {
                            updateItem(idx, { product_id: null });
                          } else {
                            selectProduct(idx, Number(val));
                          }
                        }}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                      >
                        <option value="">Custom / type below</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                      {!item.product_id && (
                        <input
                          value={item.product_name_snapshot}
                          onChange={(e) => updateItem(idx, { product_name_snapshot: e.target.value })}
                          placeholder="Product name *"
                          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                        />
                      )}
                    </div>
                  ) : (
                    <input
                      value={item.product_name_snapshot}
                      onChange={(e) => updateItem(idx, { product_name_snapshot: e.target.value })}
                      placeholder="Product name *"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                    />
                  )}
                </div>

                <div className="col-span-2">
                  <input
                    value={item.sku_snapshot ?? ""}
                    onChange={(e) => updateItem(idx, { sku_snapshot: e.target.value })}
                    placeholder="SKU"
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>

                <div className="col-span-1">
                  <input
                    type="number"
                    min={1}
                    value={item.quantity}
                    onChange={(e) => updateItem(idx, { quantity: Math.max(1, Number(e.target.value)) })}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>

                <div className="col-span-2">
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    value={item.unit_price}
                    onChange={(e) => updateItem(idx, { unit_price: Number(e.target.value) })}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>

                <div className="col-span-2">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={0.5}
                    value={item.discount_percent ?? 0}
                    onChange={(e) => updateItem(idx, { discount_percent: Number(e.target.value) })}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>

                <div className="col-span-1 flex items-center justify-end gap-1">
                  <span className="text-xs text-slate-400 whitespace-nowrap hidden lg:block">
                    {fmtAmount(lineTotal(item), currency)}
                  </span>
                  {items.length > 1 && (
                    <button
                      onClick={() => removeItem(idx)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}

            {/* Grand total */}
            <div className="flex justify-end border-t border-slate-200 pt-3 dark:border-white/10">
              <div className="text-right">
                <p className="text-xs text-slate-500 dark:text-slate-400">Total</p>
                <p className="text-xl font-bold text-slate-900 dark:text-white">
                  {fmtAmount(grandTotal, currency)}
                </p>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-1">
            <button
              onClick={handleCreate}
              disabled={createSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Quote
            </button>
            <button
              onClick={() => { setCreating(false); setItems([emptyItem()]); setSelectedLeadId(null); setLeadSearch(""); }}
              className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50 w-fit">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Quotes table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading quotes…
        </div>
      ) : filteredQuotes.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {activeTab === "All" ? "No quotes yet. Create your first quote above." : `No ${activeTab.toLowerCase()} quotes.`}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Quote #", "Lead", "Amount", "Status", "Valid Until", "Sent", "Opened", "Actions"].map(
                    (col) => (
                      <th
                        key={col}
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
                      >
                        {col}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {filteredQuotes.map((quote) => (
                  <React.Fragment key={quote.id}>
                    <tr
                      className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                        {quote.quote_number}
                      </td>
                      <td className="px-4 py-3 text-slate-800 dark:text-slate-100">
                        {leadMap[quote.lead_id] ?? `Lead #${quote.lead_id}`}
                      </td>
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                        {fmtAmount(quote.total_amount, quote.currency)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
                            STATUS_COLORS[quote.status] ?? STATUS_COLORS.draft
                          }`}
                        >
                          {quote.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {fmtDate(quote.valid_until)}
                      </td>
                      <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                        {fmtDate(quote.sent_at)}
                      </td>
                      <td className="px-4 py-3">
                        {quote.opened_at ? (
                          <div>
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                              Opened
                            </span>
                            <p className="mt-0.5 text-[10px] text-slate-500">{fmtDate(quote.opened_at)}</p>
                          </div>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-500/10 px-2 py-0.5 text-xs font-medium text-slate-500">
                            <span className="h-1.5 w-1.5 rounded-full bg-slate-500" />
                            Not opened
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {/* Generate PDF */}
                          <button
                            title="Generate PDF"
                            onClick={() => handleGeneratePDF(quote.id)}
                            disabled={actionLoading[quote.id]?.pdf}
                            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50 dark:hover:bg-white/10 dark:hover:text-slate-200"
                          >
                            {actionLoading[quote.id]?.pdf ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <FileDown className="h-4 w-4" />
                            )}
                          </button>

                          {/* Send */}
                          <button
                            title="Send quote"
                            onClick={() => {
                              setSendingQuoteId(sendingQuoteId === quote.id ? null : quote.id);
                              setSendChannels([]);
                              setSendSubject("");
                              setSendMessage("");
                            }}
                            className="rounded-lg p-1.5 text-blue-400 hover:bg-blue-50 hover:text-blue-700 dark:hover:bg-blue-500/10 dark:hover:text-blue-300"
                          >
                            <Send className="h-4 w-4" />
                          </button>

                          {/* Accept — only if sent */}
                          {quote.status === "sent" && (
                            <button
                              title="Accept quote"
                              onClick={() => handleStatusChange(quote.id, "accept")}
                              disabled={actionLoading[quote.id]?.accept}
                              className="rounded-lg p-1.5 text-emerald-500 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-50 dark:hover:bg-emerald-500/10"
                            >
                              {actionLoading[quote.id]?.accept ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <CheckCircle className="h-4 w-4" />
                              )}
                            </button>
                          )}

                          {/* Reject — if sent or draft */}
                          {(quote.status === "sent" || quote.status === "draft") && (
                            <button
                              title="Reject quote"
                              onClick={() => handleStatusChange(quote.id, "reject")}
                              disabled={actionLoading[quote.id]?.reject}
                              className="rounded-lg p-1.5 text-red-400 hover:bg-red-50 hover:text-red-700 disabled:opacity-50 dark:hover:bg-red-500/10"
                            >
                              {actionLoading[quote.id]?.reject ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <XCircle className="h-4 w-4" />
                              )}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Inline send panel */}
                    {sendingQuoteId === quote.id && (
                      <tr>
                        <td colSpan={8} className="bg-blue-50/60 dark:bg-blue-500/5 px-4 py-4">
                          <div className="space-y-3 max-w-xl">
                            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                              Send {quote.quote_number}
                            </p>

                            {/* Channels */}
                            <div className="flex items-center gap-4">
                              {["email", "whatsapp"].map((ch) => (
                                <label key={ch} className="flex items-center gap-2 cursor-pointer">
                                  <input
                                    type="checkbox"
                                    checked={sendChannels.includes(ch)}
                                    onChange={(e) =>
                                      setSendChannels((prev) =>
                                        e.target.checked
                                          ? [...prev, ch]
                                          : prev.filter((c) => c !== ch)
                                      )
                                    }
                                    className="h-4 w-4 rounded border-slate-300 text-violet-600"
                                  />
                                  <span className="text-sm capitalize text-slate-700 dark:text-slate-200">
                                    {ch}
                                  </span>
                                </label>
                              ))}
                            </div>

                            <input
                              value={sendSubject}
                              onChange={(e) => setSendSubject(e.target.value)}
                              placeholder="Subject (optional)"
                              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                            />
                            <textarea
                              value={sendMessage}
                              onChange={(e) => setSendMessage(e.target.value)}
                              rows={2}
                              placeholder="Message (optional)"
                              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                            />

                            <div className="flex gap-2">
                              <button
                                onClick={() => handleSend(quote.id)}
                                disabled={sendSaving || sendChannels.length === 0}
                                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
                              >
                                {sendSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                Send
                              </button>
                              <button
                                onClick={() => setSendingQuoteId(null)}
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
