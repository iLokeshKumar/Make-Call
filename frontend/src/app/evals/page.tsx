"use client";

import React, { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  AlertCircle,
  BarChart2,
  CheckCircle2,
  ClipboardCheck,
  Download,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EvalCase = {
  id: string;
  task: string;
  model_output: string;
  reference: string;
  rubric: string;
};

type EvalResult = {
  id: string;
  pass: boolean;
  reasoning: string;
  failures: string[];
  metadata: Record<string, unknown>;
  score_call_summary: number;
  score_lead_qualification: number;
  score_next_action: number;
  score_tool_use_honesty: number;
  score_tone_brand: number;
  score_handoff_escalation: number;
};

type EvalResponse = {
  provider: string;
  model: string;
  summary: {
    total: number;
    passed: number;
    failed: number;
    pass_rate: number;
    failed_ids: string[];
  };
  results: EvalResult[];
};

type EvalConfig = {
  active_provider: string | null;
  active_model: string | null;
  available_providers: string[];
  eval_axes: string[];
  default_thresholds: Record<string, number>;
};

// ---------------------------------------------------------------------------
// Axis definitions
// ---------------------------------------------------------------------------

const AXES: { key: keyof EvalResult; label: string; description: string }[] = [
  {
    key: "score_call_summary",
    label: "Call Summary",
    description: "Does the summary accurately capture customer intent, objections, and next steps?",
  },
  {
    key: "score_lead_qualification",
    label: "Lead Qualification",
    description: "Does the qualification decision match BANT signals in the transcript?",
  },
  {
    key: "score_next_action",
    label: "Next Action",
    description: "Is the recommended next action specific and logical given the call outcome?",
  },
  {
    key: "score_tool_use_honesty",
    label: "Tool Honesty",
    description: "Did the agent avoid fabricating product specs, pricing, or commitments?",
  },
  {
    key: "score_tone_brand",
    label: "Tone & Brand",
    description: "Was the agent professional, warm, and on-brand throughout?",
  },
  {
    key: "score_handoff_escalation",
    label: "Handoff / Close",
    description: "Did the call end with a clear CTA or correctly handle escalation requests?",
  },
];

const DEFAULT_THRESHOLDS: Record<string, number> = {
  call_summary: 4,
  lead_qualification: 4,
  next_action: 4,
  tool_use_honesty: 4,
  tone_brand: 3,
  handoff_escalation: 4,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const inputCls =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-500";
const areaCls = `${inputCls} min-h-28 resize-y`;

function scoreColor(score: number) {
  if (score >= 4) return "text-emerald-400";
  if (score === 3) return "text-amber-400";
  return "text-red-400";
}

function scoreBar(score: number) {
  const pct = (score / 5) * 100;
  const color = score >= 4 ? "bg-emerald-500" : score === 3 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-10 rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={clsx("text-xs font-mono font-bold", scoreColor(score))}>{score}/5</span>
    </div>
  );
}

function parseJsonl(text: string): EvalCase[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line, idx) => {
      const row = JSON.parse(line) as Partial<EvalCase>;
      return {
        id: row.id || `case-${idx + 1}`,
        task: row.task || "",
        model_output: row.model_output || "",
        reference: row.reference || "",
        rubric: row.rubric || "",
      };
    });
}

function exportJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

const emptyCase: EvalCase = { id: "case-1", task: "", model_output: "", reference: "", rubric: "" };

const EXAMPLE_CASES: EvalCase[] = [
  {
    id: "summary-good",
    task: "Summarize the customer's intent from this call.",
    model_output: "The customer is interested in a front-load washing machine and asked about pricing. They requested a callback tomorrow.",
    reference: "Agent: Hi, looking for a washing machine?\nLead: Yes, front-load. How much?\nAgent: Starting at ₹35,000. Shall I call tomorrow?\nLead: Yes please.",
    rubric: "Must capture product type, price inquiry, and callback request.",
  },
  {
    id: "honesty-bad",
    task: "Did the agent stay factual about product availability?",
    model_output: "Yes, the Commercia Vasari 8kg model is available and ships in 2 days.",
    reference: "Lead: Do you have Commercia Vasari?\nAgent: Let me check... I don't see that model in our catalog right now.",
    rubric: "Agent must not claim availability if the transcript shows it was unavailable.",
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EvalsPage() {
  const { user, sessionTimeout } = useAuth();
  const [cases, setCases] = useState<EvalCase[]>([emptyCase]);
  const [jsonl, setJsonl] = useState("");
  const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<EvalResponse | null>(null);
  const [config, setConfig] = useState<EvalConfig | null>(null);
  const [showGuide, setShowGuide] = useState(false);

  useEffect(() => {
    if (!user) return;
    apiFetch(`${API_BASE}/evals/config`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setConfig(d))
      .catch(() => {});
  }, [user]);

  const validCases = useMemo(
    () => cases.filter((c) => c.task.trim() && c.model_output.trim()),
    [cases],
  );

  function updateCase(i: number, key: keyof EvalCase, val: string) {
    setCases((cs) => cs.map((c, idx) => (idx === i ? { ...c, [key]: val } : c)));
  }

  function addCase() {
    setCases((cs) => [...cs, { ...emptyCase, id: `case-${cs.length + 1}` }]);
  }

  function removeCase(i: number) {
    setCases((cs) => cs.length === 1 ? cs : cs.filter((_, idx) => idx !== i));
  }

  function loadJsonl() {
    try {
      const parsed = parseJsonl(jsonl);
      if (!parsed.length) throw new Error("No JSONL rows found");
      setCases(parsed);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid JSONL");
    }
  }

  function loadExamples() {
    setCases(EXAMPLE_CASES);
    setError("");
  }

  async function runEval() {
    if (!user) return;
    if (!validCases.length) { setError("Add at least one case with task + model output."); return; }
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch(`${API_BASE}/evals/judge`, {
        method: "POST",
        body: JSON.stringify({
          cases: validCases,
          thresholds,
          concurrency: Math.min(3, validCases.length),
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Eval run failed");
      setResponse(data as EvalResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Eval run failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-400">LLM Quality</p>
          <h1 className="text-4xl font-bold tracking-tight">
            <span className="gradient-text">Evaluations</span>
          </h1>
          <div className="mt-1 flex items-center gap-3">
            <p className="text-sm font-medium text-slate-500">
              {config?.active_provider
                ? `Judge: ${config.active_provider} / ${config.active_model}`
                : "LLM-as-judge across 6 call quality axes"}
            </p>
            {config && !config.active_provider && (
              <span className="text-xs text-amber-400">No LLM key configured</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowGuide((v) => !v)}
            className="flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-400 hover:bg-white/5"
          >
            <Info className="h-3.5 w-3.5" /> What is this?
          </button>
          <button
            onClick={() => void runEval()}
            disabled={loading || validCases.length === 0}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-500/30 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
            Run Evaluation
          </button>
        </div>
      </div>

      {/* Guide panel */}
      {showGuide && (
        <div className="glass rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-violet-300">
            <BarChart2 className="h-4 w-4" /> How to use this page
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-400">
            <div className="space-y-1">
              <p className="font-semibold text-slate-300">Regression testing</p>
              <p>Changed the AI system prompt? Paste 5–10 known transcripts here and verify scores didn't drop before deploying.</p>
            </div>
            <div className="space-y-1">
              <p className="font-semibold text-slate-300">Debugging a failing axis</p>
              <p>If Handoff or Tool Honesty keeps failing in prod (CallEvalPanel), paste examples here to understand exactly why the judge penalizes them.</p>
            </div>
            <div className="space-y-1">
              <p className="font-semibold text-slate-300">vs. CallEvalPanel</p>
              <p>CallEvalPanel runs automatically on real calls. This page runs on synthetic cases you write — good for pre-deploy gates and edge case testing.</p>
            </div>
          </div>
          <div className="pt-2">
            <p className="text-xs text-slate-500 mb-2">Each case needs:</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              {[
                ["Task", "What the model was asked to do"],
                ["Model output", "What the model actually said"],
                ["Reference", "Ground truth / actual transcript"],
                ["Rubric", "Optional: extra judging rules"],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg border border-white/10 bg-white/5 p-2">
                  <p className="font-semibold text-slate-300">{k}</p>
                  <p className="text-slate-500">{v}</p>
                </div>
              ))}
            </div>
          </div>
          <button onClick={loadExamples} className="text-xs text-violet-400 hover:text-violet-300 underline underline-offset-2">
            Load example cases →
          </button>
        </div>
      )}

      {/* Axes reference */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
        {AXES.map((ax) => (
          <div key={ax.key} className="glass rounded-xl border border-white/10 p-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{ax.label}</p>
            <p className="mt-1 text-[11px] text-slate-500 leading-relaxed">{ax.description}</p>
            <p className="mt-1.5 text-[10px] text-slate-600">threshold ≥ {thresholds[ax.key.replace("score_", "")]}/5</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {/* Cases */}
        <div className="glass rounded-2xl border border-white/10 p-5 md:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
              Cases ({validCases.length} valid)
            </p>
            <button
              onClick={addCase}
              className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10"
            >
              <Plus className="h-3.5 w-3.5" /> Add case
            </button>
          </div>
          <div className="space-y-4">
            {cases.map((item, index) => (
              <div key={`${item.id}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <div className="mb-3 flex items-center gap-3">
                  <input
                    value={item.id}
                    onChange={(e) => updateCase(index, "id", e.target.value)}
                    className={`${inputCls} max-w-48`}
                    placeholder="case-id"
                  />
                  <button
                    onClick={() => removeCase(index)}
                    className="ml-auto rounded-lg p-2 text-slate-500 hover:bg-red-500/10 hover:text-red-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <p className="mb-1 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Task</p>
                    <textarea
                      value={item.task}
                      onChange={(e) => updateCase(index, "task", e.target.value)}
                      className={areaCls}
                      placeholder="What was the model asked to do?"
                    />
                  </div>
                  <div>
                    <p className="mb-1 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Model Output</p>
                    <textarea
                      value={item.model_output}
                      onChange={(e) => updateCase(index, "model_output", e.target.value)}
                      className={areaCls}
                      placeholder="What did the model actually output?"
                    />
                  </div>
                  <div>
                    <p className="mb-1 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Reference / Transcript</p>
                    <textarea
                      value={item.reference}
                      onChange={(e) => updateCase(index, "reference", e.target.value)}
                      className={areaCls}
                      placeholder="Ground truth or actual transcript to judge against"
                    />
                  </div>
                  <div>
                    <p className="mb-1 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Rubric (optional)</p>
                    <textarea
                      value={item.rubric}
                      onChange={(e) => updateCase(index, "rubric", e.target.value)}
                      className={areaCls}
                      placeholder="Extra judging rules for this specific case"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Thresholds */}
          <div className="glass rounded-2xl border border-white/10 p-5">
            <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Pass Thresholds (1–5)</p>
            {Object.entries(thresholds).map(([axis, value]) => (
              <label key={axis} className="mb-3 block">
                <span className="mb-1 block text-xs font-semibold capitalize text-slate-500">
                  {axis.replace(/_/g, " ")}
                </span>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={value}
                  onChange={(e) =>
                    setThresholds((prev) => ({
                      ...prev,
                      [axis]: Math.max(1, Math.min(5, Number(e.target.value) || 1)),
                    }))
                  }
                  className={inputCls}
                />
              </label>
            ))}
          </div>

          {/* JSONL import */}
          <div className="glass rounded-2xl border border-white/10 p-5">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">JSONL Import</p>
            <p className="mb-3 text-[10px] text-slate-600">
              One JSON object per line with keys: id, task, model_output, reference, rubric
            </p>
            <textarea
              value={jsonl}
              onChange={(e) => setJsonl(e.target.value)}
              className={`${areaCls} min-h-36`}
              placeholder={'{"id":"case-1","task":"...","model_output":"...","reference":"..."}'}
            />
            <button
              onClick={loadJsonl}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/10"
            >
              <RefreshCw className="h-4 w-4" /> Load JSONL
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <AlertCircle className="h-4 w-4" /> {error}
        </div>
      )}

      {/* Results */}
      {response && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              { label: "Total", value: response.summary.total, color: "#818cf8" },
              { label: "Passed", value: response.summary.passed, color: "#34d399" },
              { label: "Failed", value: response.summary.failed, color: "#f87171" },
              { label: "Pass Rate", value: `${Math.round(response.summary.pass_rate * 100)}%`, color: "#60a5fa" },
            ].map((item) => (
              <div
                key={item.label}
                className="glass rounded-2xl border border-white/10 p-5"
                style={{ borderLeftColor: item.color, borderLeftWidth: 3 }}
              >
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{item.label}</p>
                <p className="mt-2 text-2xl font-bold" style={{ color: item.color }}>{item.value}</p>
              </div>
            ))}
          </div>

          {/* Results table */}
          <div className="glass overflow-hidden rounded-2xl border border-white/10">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Per-Case Results</p>
                <p className="text-xs text-slate-500">
                  Judge: {response.provider} / {response.model}
                </p>
              </div>
              <button
                onClick={() => exportJson("eval-results.json", response)}
                className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/10"
              >
                <Download className="h-4 w-4" /> Export
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 bg-white/5">
                    {["Status", "ID", ...AXES.map((a) => a.label), "Failures", "Reasoning"].map((h) => (
                      <th
                        key={h}
                        className="px-3 py-3 text-[10px] font-bold uppercase tracking-widest text-slate-500 whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {response.results.map((result) => (
                    <tr key={result.id} className="hover:bg-white/5">
                      <td className="px-3 py-3">
                        {result.pass ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-1 text-xs font-semibold text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> Pass
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-1 text-xs font-semibold text-red-400">
                            <XCircle className="h-3 w-3" /> Fail
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 font-mono text-xs text-slate-300 whitespace-nowrap">{result.id}</td>
                      {AXES.map((ax) => (
                        <td key={ax.key} className="px-3 py-3">
                          {scoreBar(result[ax.key] as number)}
                        </td>
                      ))}
                      <td className="px-3 py-3 text-xs text-red-300 whitespace-nowrap">
                        {result.failures.length
                          ? result.failures.map((f) => f.replace(/_/g, " ")).join(", ")
                          : "–"}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-400 max-w-sm">{result.reasoning || "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
