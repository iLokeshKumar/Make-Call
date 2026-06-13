"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";

import CampaignStatusTimelineChart from "@/components/analytics/CampaignStatusTimelineChart";
import CampaignConversionChart from "@/components/analytics/CampaignConversionChart";
import FunnelChart from "@/components/analytics/FunnelChart";
import HorizontalMetricBars from "@/components/analytics/HorizontalMetricBars";
import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type SummaryResponse = {
  event_counts: Record<string, number>;
  channel_counts: Record<string, number>;
  campaign_funnel: Array<{ status: string; count: number; percent: number }>;
  event_timeline: Array<{ day: string; event_type: string; count: number }>;
  campaign_conversion_trends: Array<{ name: string; responded: number; sent: number; conversion_rate: number }>;
  campaign_status_over_time: Array<{ day: string; status: string; count: number }>;
  quote_timeline_export: Array<{ quote_id: number; quote_number: string; status: string; dates: Record<string, string | null> }>;
};

export default function AnalyticsSummary() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [downloadMessage, setDownloadMessage] = useState<string | null>(null);

  useEffect(() => {
    async function loadSummary() {
      if (!user) return;
      setLoading(true);
      try {
        const res = await apiFetch(`${API_BASE}/analytics/engagement-summary?days=7`, {
        });
        if (!res.ok) {
          throw new Error("Unable to load analytics");
        }
        setSummary(await res.json());
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    }
    loadSummary();
  }, [user]);

  if (!user) return null;

  const pastel = ["from-indigo-500/60 to-blue-500/30", "from-emerald-500/60 to-cyan-500/30"];
  const timelineBacklog = summary?.campaign_status_over_time.slice(-3) ?? [];
  const quotePreview = summary?.quote_timeline_export.slice(0, 3) ?? [];

  const downloadQuoteTimeline = async () => {
    if (!user) return;
    setDownloadLoading(true);
    setDownloadMessage(null);
    try {
      const res = await apiFetch(`${API_BASE}/analytics/quote/export`, {
      });
      if (!res.ok) {
        throw new Error("Failed to download quote timeline");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "quote_timeline.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setDownloadMessage("Quote timeline download started");
    } catch (err) {
      setDownloadMessage((err as Error).message);
    } finally {
      setDownloadLoading(false);
    }
  };

  return (
    <div className="space-y-4 rounded-3xl border border-white/10 bg-slate-900/40 p-6 shadow-xl shadow-black/60 backdrop-blur">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Analytics snapshot</h2>
        <Link
          href="/analytics"
          className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 hover:text-white transition"
        >
          View dashboard →
        </Link>
      </div>

      {loading ? (
        <p className="text-sm text-slate-400">Loading analytics metrics…</p>
      ) : error ? (
        <p className="text-sm text-rose-400">{error}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            {["quote.viewed", "email.open", "quote.accepted"].map((key, index) => (
              <div key={key} className={`rounded-2xl border border-white/10 bg-gradient-to-br ${pastel[index % pastel.length]} px-4 py-3 text-sm font-semibold text-white`}>
                <p className="text-xs uppercase tracking-[0.3em]">{key.replace(".", " ")}</p>
                <p className="text-2xl mt-1">{summary?.event_counts[key] ?? 0}</p>
              </div>
            ))}
          </div>

          {!!summary && Object.keys(summary.channel_counts ?? {}).length > 0 && (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-[0.3em] text-slate-400">Channel breakdown</p>
                <span className="text-[10px] text-slate-500">{Object.keys(summary.channel_counts).length} channels</span>
              </div>
              <div className="mt-3">
                <HorizontalMetricBars
                  rows={Object.entries(summary.channel_counts).map(([label, value]) => ({ label, value }))}
                  compact
                />
              </div>
            </div>
          )}

          {summary?.campaign_funnel.length ? (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
              <FunnelChart items={summary.campaign_funnel.slice(0, 4)} compact />
            </div>
          ) : null}

          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-[0.3em] text-slate-400">Campaign status timeline</p>
              <span className="text-[10px] text-slate-500">{timelineBacklog.length} records</span>
            </div>
            {timelineBacklog.length === 0 ? (
              <p className="mt-2 text-sm text-slate-300">No status history</p>
            ) : (
              <div className="mt-3">
                <CampaignStatusTimelineChart rows={summary?.campaign_status_over_time ?? []} compact limitDays={3} />
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-[0.3em] text-slate-400">Campaign conversions</p>
              <span className="text-[10px] text-slate-500">Trends</span>
            </div>
            <div className="mt-2">
              <CampaignConversionChart rows={summary?.campaign_conversion_trends ?? []} compact limit={3} />
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-[0.3em] text-slate-400">Quote timeline export</p>
              <button
                type="button"
                onClick={downloadQuoteTimeline}
                disabled={downloadLoading}
                className="text-xs font-semibold text-slate-400 hover:text-white transition"
              >
                {downloadLoading ? "Starting..." : "Download CSV"}
              </button>
            </div>
            <div className="mt-2 space-y-2 text-sm text-slate-200">
              {!quotePreview.length ? (
                <p className="text-xs text-slate-400">No quotes yet</p>
              ) : (
                quotePreview.map((quote) => (
                  <div key={quote.quote_id} className="rounded-xl border border-white/5 px-3 py-2">
                    <p className="font-semibold">{quote.quote_number}</p>
                    <p className="text-xs text-slate-400">{quote.status}</p>
                    <p className="text-xs text-slate-500">Created {quote.dates.created_at ?? "—"}</p>
                  </div>
                ))
              )}
            </div>
            {downloadMessage && (
              <p className="text-[10px] text-slate-400 mt-2">{downloadMessage}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
