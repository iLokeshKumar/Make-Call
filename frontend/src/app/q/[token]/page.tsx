"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2, XCircle, MessageSquare, ChevronDown, ChevronUp,
  Loader2, Clock, Package, BadgePercent, FileText, AlertCircle,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// Types

type QuoteInfo = {
  id: number;
  quote_number: string;
  status: string;
  currency: string;
  total_amount: string;
  valid_until: string | null;
  tracking_token: string;
  notes: string | null;
  lead_name: string | null;
  lead_email: string | null;
  lead_phone: string | null;
};

type QuoteItem = {
  id: number;
  product_name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
  discount_percent: string;
  line_total: string;
  notes: string | null;
};

type TimelineEntry = { label: string; timestamp: string };

// Helpers

const fmt = (v: string, currency: string) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(v));

const fmtDate = (v: string | null) =>
  v ? new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  draft:       { label: "Draft",       color: "text-slate-500",   bg: "bg-slate-100" },
  pending:     { label: "Pending",     color: "text-amber-700",   bg: "bg-amber-50" },
  sent:        { label: "Sent",        color: "text-blue-700",    bg: "bg-blue-50" },
  accepted:    { label: "Accepted",    color: "text-emerald-700", bg: "bg-emerald-50" },
  rejected:    { label: "Declined",    color: "text-red-700",     bg: "bg-red-50" },
  negotiation: { label: "In Review",   color: "text-violet-700",  bg: "bg-violet-50" },
  expired:     { label: "Expired",     color: "text-slate-500",   bg: "bg-slate-100" },
};

// Main Page

export default function PublicQuotePage() {
  const params = useParams();
  const token = params?.token as string;

  const [quote, setQuote]       = useState<QuoteInfo | null>(null);
  const [items, setItems]       = useState<QuoteItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);

  // Action state
  const [acting, setActing]                 = useState<"accept" | "reject" | "negotiate" | null>(null);
  const [done, setDone]                     = useState<string | null>(null);

  // Negotiate panel
  const [showNegotiate, setShowNegotiate]   = useState(false);
  const [negMessage, setNegMessage]         = useState("");
  const [negDiscount, setNegDiscount]       = useState("");
  const [negError, setNegError]             = useState("");

  // Timeline toggle
  const [showTimeline, setShowTimeline]     = useState(false);

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/tracking/quote/info/${token}`)
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || "Not found")))
      .then(data => {
        setQuote(data.quote);
        setItems(data.items ?? []);
        setTimeline(data.timeline ?? []);
      })
      .catch(e => setError(typeof e === "string" ? e : "Could not load quote"))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleAccept() {
    setActing("accept");
    try {
      const r = await fetch(`${API_BASE}/tracking/quote/accept/${token}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json()).detail || "Failed");
      setDone("accepted");
      setQuote(q => q ? { ...q, status: "accepted" } : q);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setActing(null); }
  }

  async function handleReject() {
    setActing("reject");
    try {
      const r = await fetch(`${API_BASE}/tracking/quote/reject/${token}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json()).detail || "Failed");
      setDone("rejected");
      setQuote(q => q ? { ...q, status: "rejected" } : q);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setActing(null); }
  }

  async function handleNegotiate() {
    setNegError("");
    if (!negMessage.trim()) { setNegError("Please describe what you'd like changed."); return; }
    setActing("negotiate");
    try {
      const r = await fetch(`${API_BASE}/tracking/quote/negotiate/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: negMessage.trim(),
          requested_discount: negDiscount ? Number(negDiscount) : null,
        }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "Failed");
      setDone("negotiation");
      setQuote(q => q ? { ...q, status: "negotiation" } : q);
    } catch (e) { setNegError(e instanceof Error ? e.message : "Failed"); }
    finally { setActing(null); }
  }

  const isClosed = done || (quote && ["accepted", "rejected", "negotiation"].includes(quote.status));
  const statusMeta = quote ? (STATUS_META[quote.status] ?? STATUS_META.pending) : null;

  // Loading / error

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
    </div>
  );

  if (error && !quote) return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="text-center space-y-3">
        <AlertCircle className="h-10 w-10 text-red-400 mx-auto" />
        <p className="text-slate-700 font-medium">{error}</p>
        <p className="text-slate-400 text-sm">This quote link may have expired or is invalid.</p>
      </div>
    </div>
  );

  if (!quote) return null;

  // Done screen

  if (done === "accepted") return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 to-teal-50">
      <div className="text-center space-y-4 p-8 max-w-sm">
        <CheckCircle2 className="h-16 w-16 text-emerald-500 mx-auto" />
        <h2 className="text-2xl font-bold text-slate-800">Quote Accepted!</h2>
        <p className="text-slate-600">Thank you, {quote.lead_name}. We've received your acceptance of <strong>{quote.quote_number}</strong>. Our team will be in touch shortly.</p>
      </div>
    </div>
  );

  if (done === "rejected") return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-rose-50">
      <div className="text-center space-y-4 p-8 max-w-sm">
        <XCircle className="h-16 w-16 text-red-400 mx-auto" />
        <h2 className="text-2xl font-bold text-slate-800">Quote Declined</h2>
        <p className="text-slate-600">We understand. If you'd like to revisit this or discuss alternatives, please reach out to us directly.</p>
      </div>
    </div>
  );

  if (done === "negotiation") return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-violet-50 to-indigo-50">
      <div className="text-center space-y-4 p-8 max-w-sm">
        <MessageSquare className="h-16 w-16 text-violet-500 mx-auto" />
        <h2 className="text-2xl font-bold text-slate-800">Request Sent!</h2>
        <p className="text-slate-600">Your message has been sent to our team. We'll review your request and get back to you soon.</p>
      </div>
    </div>
  );

  // Main quote view

  return (
    <div className="min-h-screen bg-slate-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-5">

        {/* Header card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="bg-gradient-to-r from-slate-800 to-slate-700 px-6 py-5 text-white">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-1">Quotation</p>
            <h1 className="text-2xl font-bold">{quote.quote_number}</h1>
            {quote.lead_name && <p className="text-slate-300 text-sm mt-0.5">Prepared for {quote.lead_name}</p>}
          </div>
          <div className="px-6 py-4 flex flex-wrap gap-6 text-sm">
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-widest mb-0.5">Status</p>
              <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${statusMeta?.bg} ${statusMeta?.color}`}>
                {statusMeta?.label}
              </span>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-widest mb-0.5">Total</p>
              <p className="text-lg font-bold text-slate-800">{fmt(quote.total_amount, quote.currency)}</p>
            </div>
            {quote.valid_until && (
              <div>
                <p className="text-[10px] text-slate-400 uppercase tracking-widest mb-0.5">Valid Until</p>
                <p className="flex items-center gap-1 text-slate-700 font-medium">
                  <Clock className="h-3.5 w-3.5 text-amber-500" />
                  {fmtDate(quote.valid_until)}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Line items */}
        {items.length > 0 && (
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
              <Package className="h-4 w-4 text-violet-500" />
              <p className="text-sm font-semibold text-slate-700">Items</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-[10px] uppercase tracking-widest text-slate-400">
                    <th className="px-5 py-2.5 text-left">Product</th>
                    <th className="px-4 py-2.5 text-right">Qty</th>
                    <th className="px-4 py-2.5 text-right">Unit Price</th>
                    <th className="px-4 py-2.5 text-right">Discount</th>
                    <th className="px-5 py-2.5 text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map(it => (
                    <tr key={it.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3">
                        <p className="font-medium text-slate-800">{it.product_name}</p>
                        {it.sku && <p className="text-[10px] text-slate-400 mt-0.5">SKU: {it.sku}</p>}
                        {it.notes && <p className="text-xs text-slate-500 mt-0.5 italic">{it.notes}</p>}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600">{it.quantity}</td>
                      <td className="px-4 py-3 text-right text-slate-600">{fmt(it.unit_price, quote.currency)}</td>
                      <td className="px-4 py-3 text-right">
                        {Number(it.discount_percent) > 0 ? (
                          <span className="inline-flex items-center gap-1 text-emerald-600 font-medium">
                            <BadgePercent className="h-3 w-3" />{it.discount_percent}%
                          </span>
                        ) : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-5 py-3 text-right font-semibold text-slate-800">{fmt(it.line_total, quote.currency)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-slate-50 border-t border-slate-200">
                    <td colSpan={4} className="px-5 py-3 text-sm font-semibold text-slate-600 text-right">Total</td>
                    <td className="px-5 py-3 text-right text-base font-bold text-slate-900">{fmt(quote.total_amount, quote.currency)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )}

        {/* Notes */}
        {quote.notes && (
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-6 py-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="h-4 w-4 text-slate-400" />
              <p className="text-sm font-semibold text-slate-600">Notes</p>
            </div>
            <p className="text-sm text-slate-600 whitespace-pre-wrap">{quote.notes}</p>
          </div>
        )}

        {/* Already actioned */}
        {quote.status === "accepted" && (
          <div className="rounded-2xl bg-emerald-50 border border-emerald-200 px-6 py-5 flex items-center gap-3">
            <CheckCircle2 className="h-6 w-6 text-emerald-500 flex-shrink-0" />
            <p className="text-emerald-800 font-medium text-sm">You've already accepted this quote. Our team will be in touch.</p>
          </div>
        )}
        {quote.status === "rejected" && (
          <div className="rounded-2xl bg-red-50 border border-red-200 px-6 py-5 flex items-center gap-3">
            <XCircle className="h-6 w-6 text-red-400 flex-shrink-0" />
            <p className="text-red-800 font-medium text-sm">This quote was declined. Contact us if you'd like to discuss further.</p>
          </div>
        )}
        {quote.status === "negotiation" && (
          <div className="rounded-2xl bg-violet-50 border border-violet-200 px-6 py-5 flex items-center gap-3">
            <MessageSquare className="h-6 w-6 text-violet-500 flex-shrink-0" />
            <p className="text-violet-800 font-medium text-sm">Your change request is being reviewed. We'll update you soon.</p>
          </div>
        )}

        {/* Action buttons */}
        {!isClosed && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={handleAccept}
                disabled={!!acting}
                className="flex items-center justify-center gap-2 rounded-2xl bg-emerald-500 hover:bg-emerald-600 active:bg-emerald-700 text-white font-semibold py-4 text-sm transition-colors disabled:opacity-50"
              >
                {acting === "accept" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Accept Quote
              </button>
              <button
                onClick={handleReject}
                disabled={!!acting}
                className="flex items-center justify-center gap-2 rounded-2xl bg-white hover:bg-red-50 active:bg-red-100 border border-red-200 text-red-600 font-semibold py-4 text-sm transition-colors disabled:opacity-50"
              >
                {acting === "reject" ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                Decline
              </button>
            </div>

            {/* Request changes toggle */}
            <button
              onClick={() => setShowNegotiate(v => !v)}
              className="w-full flex items-center justify-between gap-2 rounded-2xl bg-white hover:bg-violet-50 border border-violet-200 text-violet-700 font-semibold px-5 py-4 text-sm transition-colors"
            >
              <span className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Request Changes or Discount
              </span>
              {showNegotiate ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>

            {showNegotiate && (
              <div className="bg-white rounded-2xl border border-violet-200 px-6 py-5 space-y-4">
                <p className="text-sm text-slate-500">
                  Tell us what you'd like changed — a discount, removal of an item, a revised quantity, or anything else. Our team will review and send a revised quote.
                </p>

                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1.5">
                    Your message <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    value={negMessage}
                    onChange={e => setNegMessage(e.target.value)}
                    placeholder="e.g. Can you offer a 10% discount on the total? Or remove item 2 from the list."
                    rows={4}
                    className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1.5">
                    Requested discount % <span className="text-slate-400">(optional)</span>
                  </label>
                  <div className="relative max-w-[160px]">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.5"
                      value={negDiscount}
                      onChange={e => setNegDiscount(e.target.value)}
                      placeholder="e.g. 15"
                      className="w-full rounded-xl border border-slate-200 pl-4 pr-8 py-2.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-violet-400"
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">%</span>
                  </div>
                </div>

                {negError && (
                  <p className="text-red-500 text-xs flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" />{negError}
                  </p>
                )}

                <button
                  onClick={handleNegotiate}
                  disabled={!!acting}
                  className="flex items-center gap-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold px-5 py-2.5 text-sm transition-colors disabled:opacity-50"
                >
                  {acting === "negotiate" ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />}
                  Send Request
                </button>
              </div>
            )}
          </div>
        )}

        {/* Timeline */}
        {timeline.length > 0 && (
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <button
              onClick={() => setShowTimeline(v => !v)}
              className="w-full flex items-center justify-between px-6 py-4 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <span>Quote Timeline</span>
              {showTimeline ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {showTimeline && (
              <div className="px-6 pb-5 space-y-3 border-t border-slate-100 pt-4">
                {timeline.map((t, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className="mt-1.5 h-2 w-2 rounded-full bg-violet-400 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-slate-700">{t.label}</p>
                      <p className="text-[11px] text-slate-400">{new Date(t.timestamp).toLocaleString("en-IN")}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <p className="text-center text-[11px] text-slate-400 pb-4">
          Powered by Rio CRM · This quote was prepared specifically for {quote.lead_name ?? "you"}
        </p>
      </div>
    </div>
  );
}
