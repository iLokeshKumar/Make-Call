"use client";

import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BarChart2, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type EvalResult = {
  id: number;
  interaction_id: number;
  judge_provider: string;
  judge_model: string;
  score_call_summary: number | null;
  score_lead_qualification: number | null;
  score_next_action: number | null;
  score_tool_use_honesty: number | null;
  score_tone_brand: number | null;
  score_handoff_escalation: number | null;
  score_overall: number | null;
  passed: boolean;
  reasoning: string | null;
  failures: string[];
  ran_at: string | null;
};

const AXES: { key: keyof EvalResult; label: string; color: string }[] = [
  { key: "score_call_summary",       label: "Call Summary",       color: "bg-blue-500" },
  { key: "score_lead_qualification", label: "Lead Qualification", color: "bg-violet-500" },
  { key: "score_next_action",        label: "Next Action",        color: "bg-amber-500" },
  { key: "score_tool_use_honesty",   label: "Tool Honesty",       color: "bg-emerald-500" },
  { key: "score_tone_brand",         label: "Tone & Brand",       color: "bg-sky-500" },
  { key: "score_handoff_escalation", label: "Handoff / Close",    color: "bg-rose-500" },
];

function ScoreBar({ score, color, failed }: { score: number | null | undefined; color: string; failed: boolean }) {
  const pct = score != null ? (score / 5) * 100 : 0;
  const label = score == null ? "–" : `${score}/5`;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-slate-200 dark:bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${failed ? "bg-red-400" : color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-mono w-8 text-right ${failed ? "text-red-500" : "text-slate-600 dark:text-slate-300"}`}>
        {label}
      </span>
    </div>
  );
}

function OverallBadge({ score, passed }: { score: number | null; passed: boolean }) {
  if (score == null) return null;
  const pct = Math.round((score / 5) * 100);
  const color = passed ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400";
  return (
    <div className={`flex items-center gap-1.5 text-sm font-semibold ${color}`}>
      {passed
        ? <CheckCircle2 className="w-4 h-4" />
        : <XCircle className="w-4 h-4" />}
      {pct}% overall
    </div>
  );
}

type Props = {
  interactionId: number;
  onSessionTimeout?: () => void;
};

export default function CallEvalPanel({ interactionId, onSessionTimeout }: Props) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const evalQuery = useQuery<EvalResult>({
    queryKey: ["call-eval", interactionId],
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/evals/call/${interactionId}`);
      if (res.status === 401) { onSessionTimeout?.(); throw new Error("unauthorized"); }
      if (res.status === 404) throw new Error("no_eval");
      if (!res.ok) throw new Error(`Server ${res.status}`);
      return res.json();
    },
    retry: false,
    staleTime: 60_000,
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      const res = await apiFetch(`${API_BASE}/evals/call/${interactionId}/run`, { method: "POST" });
      if (res.status === 401) { onSessionTimeout?.(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error(`Server ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      // Poll for result after 4 seconds (judge is async)
      setTimeout(() => qc.invalidateQueries({ queryKey: ["call-eval", interactionId] }), 4000);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["call-eval", interactionId] }), 10000);
    },
  });

  const data = evalQuery.data;
  const noEval = evalQuery.error?.message === "no_eval";
  const loading = evalQuery.isLoading;
  const running = runMutation.isPending;

  return (
    <div className="mt-3 border border-slate-200 dark:border-white/10 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 dark:bg-white/5 hover:bg-slate-100 dark:hover:bg-white/10 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <BarChart2 className="w-4 h-4 text-violet-500" />
          AI Evaluation Judge
          {data && (
            <OverallBadge score={data.score_overall} passed={data.passed} />
          )}
          {noEval && (
            <span className="text-xs text-slate-400 font-normal">not run yet</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
          {data && (
            <span className="text-xs text-slate-400">
              {data.judge_provider}/{data.judge_model.split("-").slice(0, 2).join("-")}
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="p-4 space-y-4 bg-white dark:bg-slate-900/50">
          {/* Run / Re-run button */}
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-500">
              {data?.ran_at
                ? `Last run: ${new Date(data.ran_at).toLocaleString()}`
                : noEval
                  ? "No evaluation has been run for this call yet."
                  : ""}
            </p>
            <button
              onClick={() => runMutation.mutate()}
              disabled={running}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50 transition-colors"
            >
              {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              {data ? "Re-run evaluation" : "Run evaluation"}
            </button>
          </div>

          {running && !data && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Evaluation in progress — results appear in ~10s
            </div>
          )}

          {data && (
            <>
              {/* Axis scores */}
              <div className="space-y-2.5">
                {AXES.map(({ key, label, color }) => {
                  const score = data[key] as number | null;
                  const failed = data.failures?.includes(key.replace("score_", ""));
                  return (
                    <div key={key}>
                      <div className="flex justify-between text-xs text-slate-500 mb-1">
                        <span>{label}</span>
                        {failed && (
                          <span className="text-red-500 font-medium">failed</span>
                        )}
                      </div>
                      <ScoreBar score={score} color={color} failed={!!failed} />
                    </div>
                  );
                })}
              </div>

              {/* Reasoning */}
              {data.reasoning && (
                <div className="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-white/5 rounded-lg p-3 leading-relaxed whitespace-pre-wrap">
                  {data.reasoning}
                </div>
              )}

              {/* Failures summary */}
              {data.failures?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {data.failures.map(f => (
                    <span key={f} className="text-xs px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
                      {f.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
