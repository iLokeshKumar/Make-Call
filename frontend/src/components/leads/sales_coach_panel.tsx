"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Award, Brain, Loader2, RefreshCw, TrendingUp, Zap } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type CoachScore = {
  id: number;
  interaction_id: number;
  score_rapport?: number | null;
  score_discovery?: number | null;
  score_objection_handling?: number | null;
  score_value_proposition?: number | null;
  score_closing?: number | null;
  score_overall?: number | null;
  strengths?: string | null;
  weaknesses?: string | null;
  prompt_suggestion?: string | null;
  prompt_applied: boolean;
  created_at?: string | null;
};

type Props = {
  interactionId: number;
  onSessionTimeout?: () => void;
};

const DIMENSIONS: { key: keyof CoachScore; label: string; color: string }[] = [
  { key: "score_rapport",            label: "Rapport",         color: "bg-violet-500" },
  { key: "score_discovery",          label: "Discovery",       color: "bg-blue-500" },
  { key: "score_objection_handling", label: "Objections",      color: "bg-amber-500" },
  { key: "score_value_proposition",  label: "Value Prop",      color: "bg-emerald-500" },
  { key: "score_closing",            label: "Closing",         color: "bg-rose-500" },
];

function ScoreBar({ score, color }: { score: number | null | undefined; color: string }) {
  const pct = ((score ?? 0) / 10) * 100;
  const label = score == null ? "–" : `${score}/10`;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-slate-200 dark:bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-slate-600 dark:text-slate-300 w-8 text-right">
        {label}
      </span>
    </div>
  );
}

function overallColor(score: number | null | undefined): string {
  if (score == null) return "text-slate-400";
  if (score >= 8) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 6) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

export default function SalesCoachPanel({ interactionId, onSessionTimeout }: Props) {
  const [score, setScore] = useState<CoachScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showSuggestion, setShowSuggestion] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchScore = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      else setRefreshing(true);
      try {
        const res = await apiFetch(`${API_BASE}/crm/coach/scores/${interactionId}`, {
        });
        if (res.status === 401) { onSessionTimeout?.(); return; }
        if (!res.ok) return;
        const data = await res.json();
        if (data) {
          setScore(data);
          // Score arrived — stop polling
          if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; }
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [interactionId, onSessionTimeout]
  );

  useEffect(() => {
    fetchScore();
    // If no score yet, poll every 15s for up to 3 minutes (worker may still be processing)
    const start = Date.now();
    const poll = () => {
      if (score) return;
      if (Date.now() - start > 3 * 60 * 1000) return;
      pollRef.current = setTimeout(() => { fetchScore(true); poll(); }, 15_000);
    };
    poll();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactionId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500 py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading coach score...
      </div>
    );
  }

  if (!score) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-dashed border-slate-300 dark:border-slate-700 px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
          <span>Score being generated — usually ready within a minute...</span>
        </div>
        <button
          onClick={() => fetchScore(true)}
          disabled={refreshing}
          className="text-xs text-violet-500 hover:underline disabled:opacity-50"
        >
          {refreshing ? "Checking..." : "Check now"}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl glass border border-violet-200/60 dark:border-violet-500/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-500/10">
          <Brain className="h-4 w-4 text-violet-600 dark:text-violet-400" />
        </div>
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-white">AI Sales Coach</h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            Post-call performance analysis
            {score.prompt_applied && (
              <span className="ml-2 text-emerald-600 dark:text-emerald-400 font-semibold">
                · Prompt auto-tuned
              </span>
            )}
          </p>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <div className="text-right">
            <div className={`text-2xl font-bold ${overallColor(score.score_overall)}`}>
              {score.score_overall ?? "–"}<span className="text-base font-normal text-slate-400">/10</span>
            </div>
            <div className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider">overall</div>
          </div>
          <button
            onClick={() => fetchScore(true)}
            disabled={refreshing}
            className="text-slate-400 hover:text-violet-500 transition"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Dimension bars */}
        <div className="space-y-2.5">
          {DIMENSIONS.map(({ key, label, color }) => (
            <div key={key} className="grid grid-cols-[90px_1fr] items-center gap-3">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
              <ScoreBar score={score[key] as number | null} color={color} />
            </div>
          ))}
        </div>

        {/* Strength / Weakness */}
        {(score.strengths || score.weaknesses) && (
          <div className="space-y-2 rounded-xl bg-slate-50 dark:bg-slate-900/30 border border-slate-200 dark:border-white/10 p-3">
            {score.strengths && (
              <div className="flex gap-2 text-xs">
                <Award className="h-3.5 w-3.5 text-emerald-500 flex-shrink-0 mt-0.5" />
                <span className="text-slate-700 dark:text-slate-300">
                  <strong className="text-emerald-700 dark:text-emerald-400">Strength: </strong>
                  {score.strengths}
                </span>
              </div>
            )}
            {score.weaknesses && (
              <div className="flex gap-2 text-xs">
                <TrendingUp className="h-3.5 w-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                <span className="text-slate-700 dark:text-slate-300">
                  <strong className="text-amber-700 dark:text-amber-400">Improve: </strong>
                  {score.weaknesses}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Prompt suggestion */}
        {score.prompt_suggestion && (
          <div>
            <button
              onClick={() => setShowSuggestion(!showSuggestion)}
              className="flex items-center gap-1.5 text-xs font-semibold text-violet-600 dark:text-violet-400 hover:underline"
            >
              <Zap className="h-3 w-3" />
              {showSuggestion ? "Hide" : "Show"} prompt suggestion
            </button>
            {showSuggestion && (
              <div className="mt-2 rounded-xl bg-violet-50 dark:bg-violet-500/10 border border-violet-200 dark:border-violet-500/30 p-3 text-xs text-slate-700 dark:text-slate-300 leading-relaxed font-mono">
                {score.prompt_suggestion}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
