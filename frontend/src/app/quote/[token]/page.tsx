"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type QuoteInfo = {
  quote: {
    id: number;
    quote_number: string;
    status: string;
    currency: string;
    total_amount: string;
    valid_until?: string;
    notes?: string | null;
    lead_name?: string | null;
    lead_email?: string | null;
  };
  timeline: { label: string; timestamp: string }[];
  events: { event_type: string; channel?: string | null; payload?: Record<string, unknown>; created_at: string }[];
};

type QuoteResponseMessage = { type: "success" | "error"; text: string };

export default function QuotePublicPage({ params }: { params: { token: string } }) {
  const [quoteInfo, setQuoteInfo] = useState<QuoteInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<QuoteResponseMessage | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    async function loadQuote() {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/tracking/quote/info/${params.token}`);
        if (!res.ok) {
          throw new Error("Quote not found");
        }
        const payload = await res.json();
        setQuoteInfo(payload);
      } catch (error) {
        setMessage({ type: "error", text: "Unable to load quote details." });
      } finally {
        setLoading(false);
      }
    }
    loadQuote();
  }, [params.token]);

  const timeline = useMemo(() => {
    if (!quoteInfo) return [];
    return quoteInfo.timeline;
  }, [quoteInfo]);

  const handleAction = async (action: "accept" | "reject") => {
    if (!quoteInfo) return;
    setActionLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/tracking/quote/${action}/${params.token}`, {
        method: "POST",
      });
      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || "Unexpected response");
      }
      setMessage({ type: "success", text: `Quote ${payload.status}` });
      // refresh status
      const infoRes = await fetch(`${API_BASE}/tracking/quote/info/${params.token}`);
      if (infoRes.ok) {
        setQuoteInfo(await infoRes.json());
      }
    } catch (error) {
      setMessage({ type: "error", text: (error as Error).message });
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <p className="text-xl text-white">Loading quote details…</p>
      </div>
    );
  }

  if (!quoteInfo) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950 px-4 text-center">
        <p className="max-w-xl rounded-2xl bg-white/10 px-6 py-5 text-lg text-white shadow-lg shadow-black/40">Quote cannot be found. Please verify the link.</p>
      </div>
    );
  }

  const { quote } = quoteInfo;
  const isFinalized = ["accepted", "rejected"].includes(quote.status);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 px-4 py-16 text-white">
      <div className="mx-auto max-w-3xl space-y-8 rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl shadow-black/60 backdrop-blur">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 text-lg font-bold text-white">
              R
            </div>
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Rio CRM</p>
              <h1 className="text-2xl font-bold">{quote.quote_number}</h1>
            </div>
          </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/10 p-4">
            <p className="text-sm uppercase tracking-[0.2em] text-slate-300">Total</p>
            <p className="mt-2 text-3xl font-semibold">
              {quote.currency} {quote.total_amount}
            </p>
            <p className="text-sm text-slate-300">Valid until {quote.valid_until ? new Date(quote.valid_until).toLocaleDateString() : "—"}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/10 p-4">
            <p className="text-sm uppercase tracking-[0.2em] text-slate-300">Buyer</p>
            <p className="mt-1 text-lg font-semibold">{quote.lead_name || "Valued customer"}</p>
            <p className="text-sm text-slate-300">{quote.lead_email || "Email not available"}</p>
            {quote.notes && (
              <p className="mt-2 text-sm text-slate-100">{quote.notes}</p>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Quote status</h2>
            <span className="text-sm text-slate-300">{quote.status.replace(/_/g, " ")}</span>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => handleAction("accept")}
              disabled={isFinalized || actionLoading}
              className={`flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition ${
                isFinalized
                  ? "cursor-not-allowed border border-slate-500/50 bg-slate-700 text-slate-400"
                  : "border border-emerald-500/60 bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30"
              }`}
            >
              <CheckCircle2 className="h-4 w-4" />
              Accept
            </button>
            <button
              type="button"
              onClick={() => handleAction("reject")}
              disabled={isFinalized || actionLoading}
              className={`flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition ${
                isFinalized
                  ? "cursor-not-allowed border border-slate-500/50 bg-slate-700 text-slate-400"
                  : "border border-rose-500/60 bg-rose-500/20 text-rose-200 hover:bg-rose-500/30"
              }`}
            >
              <XCircle className="h-4 w-4" />
              Reject
            </button>
          </div>
          {message && (
            <div
              className={`rounded-2xl border px-4 py-3 text-sm ${
                message.type === "success" ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-300" : "border-rose-400/50 bg-rose-500/10 text-rose-200"
              }`}
            >
              {message.text}
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-2xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Timeline</h3>
          {timeline.length === 0 && <p className="text-sm text-slate-300">No timeline available yet.</p>}
          <ul className="space-y-2">
            {timeline.map((entry) => (
              <li key={`${entry.label}-${entry.timestamp}`} className="flex items-center justify-between text-sm text-slate-200">
                <span>{entry.label}</span>
                <span className="text-xs text-slate-400">{new Date(entry.timestamp).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-3 rounded-2xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Engagement events</h3>
          <div className="grid gap-3">
            {quoteInfo.events.length === 0 && <p className="text-sm text-slate-300">No tracked events yet.</p>}
            {quoteInfo.events.map((event) => (
              <div key={event.created_at + event.event_type} className="rounded-xl border border-white/5 bg-white/10 px-4 py-3 text-sm text-slate-200">
                <p className="font-semibold">{event.event_type}</p>
                <p className="text-xs text-slate-400">{new Date(event.created_at).toLocaleString()}</p>
                {event.channel && <p className="text-xs text-slate-400">Channel: {event.channel}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
