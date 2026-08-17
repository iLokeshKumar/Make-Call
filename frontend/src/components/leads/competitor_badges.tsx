"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";


type Mention = {
  id: number;
  competitor_name: string;
  mention_snippet?: string | null;
  source: string;
  detected_at?: string | null;
};

type Props = {
  leadId: number;
  onSessionTimeout?: () => void;
};

export default function CompetitorBadges({ leadId, onSessionTimeout }: Props) {
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  const fetchMentions = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/competitors`, {
      });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      if (!res.ok) return;
      const data = await res.json();
      setMentions(data.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [leadId, onSessionTimeout]);

  useEffect(() => { fetchMentions(); }, [fetchMentions]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading competitor signals...
      </div>
    );
  }

  if (mentions.length === 0) return null;

  // Deduplicate by competitor name, keep count
  const counts: Record<string, { count: number; latest: Mention }> = {};
  for (const m of mentions) {
    const key = m.competitor_name;
    if (!counts[key]) counts[key] = { count: 0, latest: m };
    counts[key].count++;
    if ((m.detected_at ?? "") > (counts[key].latest.detected_at ?? "")) {
      counts[key].latest = m;
    }
  }

  const entries = Object.entries(counts).sort((a, b) => b[1].count - a[1].count);

  return (
    <div className="rounded-2xl glass border border-amber-200/60 dark:border-amber-500/20 p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-500/10">
          <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        </div>
        <h3 className="font-semibold text-slate-900 dark:text-white">Competitor Signals</h3>
        <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
          {mentions.length} mention{mentions.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {entries.map(([name, { count, latest }]) => (
          <div key={name} className="relative">
            <button
              onClick={() => setExpanded(expanded === latest.id ? null : latest.id)}
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 px-3 py-1 text-xs font-semibold text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-500/20 transition"
            >
              <AlertTriangle className="h-3 w-3" />
              {name}
              {count > 1 && (
                <span className="ml-1 rounded-full bg-amber-500 text-white px-1.5 py-0.5 text-[10px] font-bold">
                  {count}
                </span>
              )}
            </button>

            {expanded === latest.id && latest.mention_snippet && (
              <div className="absolute left-0 top-8 z-10 w-72 rounded-xl border border-amber-200 dark:border-amber-500/30 bg-white dark:bg-slate-900 p-3 shadow-xl text-xs text-slate-700 dark:text-slate-300">
                <p className="font-semibold text-amber-700 dark:text-amber-400 mb-1">Transcript snippet</p>
                <p className="italic">"{latest.mention_snippet}"</p>
                <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
                  Source: {latest.source} · {latest.detected_at ? new Date(latest.detected_at).toLocaleString() : "unknown"}
                </p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
