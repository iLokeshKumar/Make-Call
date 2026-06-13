"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";
import {
    Phone, Clock, Mail, MessageCircle, MessageSquare,
    PlayCircle, Loader2, X, ArrowUpRight, ArrowDownLeft,
    Mic, MicOff, ChevronLeft, ChevronRight, Code2, Copy, Check,
    Activity, Wrench, Zap,
} from "lucide-react";
import clsx from "clsx";
import { apiFetch } from "@/utils/apiFetch";
import WaveformPlayer from "@/components/leads/waveform_player";
import CallEvalPanel from "@/components/leads/call_eval_panel";

interface ChildInteraction {
    id: number;
    channel?: string | null;
    direction?: string | null;
    type?: string | null;
    created_at?: string | null;
    content?: string | null;
}

interface Interaction {
    id: number;
    type: string;
    channel?: string | null;
    direction?: string | null;
    status?: string;
    delivery_status?: string | null;
    content?: string | null;
    transcript?: string | null;
    recording_url?: string | null;
    recording_duration?: number | null;
    timestamp?: string;
    started_at?: string;
    ended_at?: string | null;
    created_at?: string;
    lead_id?: number | null;
    lead_name?: string;
    source?: string | null;
    eval_score?: number | null;
    eval_passed?: boolean | null;
    csat_rating?: number | null;
    parent_interaction_id?: number | null;
    children?: ChildInteraction[];
    metadata_json?: Record<string, unknown> | null;
}

interface DialerResult {
    attempted: number;
    skipped: number;
    results: Array<{ task_id: number; status: string; reason?: string }>;
}

const TYPE_ICON: Record<string, React.ReactNode> = {
    email: <Mail className="h-4 w-4" />,
    whatsapp: <MessageCircle className="h-4 w-4" />,
    sms: <MessageSquare className="h-4 w-4" />,
};

const TYPE_COLOR: Record<string, string> = {
    email: "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400",
    whatsapp: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400",
    sms: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
};

const STATUS_COLOR: Record<string, string> = {
    ended: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
    completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    active: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
    failed: "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400",
    busy: "bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400",
    no_answer: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
    cancelled: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

function typeIcon(type: string) {
    const key = type.toLowerCase();
    return TYPE_ICON[key] ?? <Phone className="h-4 w-4" />;
}

function typeColor(type: string) {
    const key = type.toLowerCase();
    return TYPE_COLOR[key] ?? "bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400";
}

function statusBadge(status?: string) {
    if (!status || status === "logged") return null;
    const color = STATUS_COLOR[status] ?? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400";
    return (
        <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", color)}>
            {status.replace("_", " ")}
        </span>
    );
}

function formatDuration(seconds?: number | null) {
    if (!seconds || seconds <= 0) return null;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatDate(call: Interaction) {
    const ts = call.started_at ?? call.created_at ?? call.timestamp;
    if (!ts) return "—";
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const PROVIDER_COLOR: Record<string, string> = {
    twilio: "bg-red-50 text-red-600 border-red-200 dark:bg-red-900/20 dark:text-red-400 dark:border-red-800/40",
    plivo: "bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/20 dark:text-orange-400 dark:border-orange-800/40",
    vobiz: "bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/20 dark:text-blue-400 dark:border-blue-800/40",
    exotel: "bg-teal-50 text-teal-600 border-teal-200 dark:bg-teal-900/20 dark:text-teal-400 dark:border-teal-800/40",
    enablex: "bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-900/20 dark:text-purple-400 dark:border-purple-800/40",
    inbound: "bg-emerald-50 text-emerald-600 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800/40",
};

function providerBadge(source?: string | null) {
    if (!source) return <span className="text-slate-300 dark:text-slate-700">—</span>;
    const key = source.toLowerCase();
    const color = PROVIDER_COLOR[key] ?? "bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700";
    return (
        <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", color)}>
            {source}
        </span>
    );
}

function FeedbackCell({ call }: { call: Interaction }) {
    const hasEval = call.eval_score != null;
    const hasCsat = call.csat_rating != null;
    if (!hasEval && !hasCsat) return <span className="text-slate-300 dark:text-slate-700">—</span>;
    return (
        <div className="flex flex-col gap-1">
            {hasEval && (
                <span className={clsx(
                    "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold",
                    call.eval_passed
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                        : "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
                )}>
                    {Math.round(((call.eval_score ?? 0) / 5) * 100)}% {call.eval_passed ? "✓" : "✗"}
                </span>
            )}
            {hasCsat && (
                <span className="inline-flex items-center gap-0.5 text-[11px] text-amber-500">
                    {"★".repeat(call.csat_rating ?? 0)}{"☆".repeat(5 - (call.csat_rating ?? 0))}
                </span>
            )}
        </div>
    );
}

function callTitle(call: Interaction) {
    if (call.type === "call" || call.type === "call_completed" || call.type === "call_summary") {
        return call.lead_name || "Unknown Lead";
    }
    return call.lead_name || call.type;
}

const CHILD_CHANNEL_ICON: Record<string, React.ReactNode> = {
    email: <Mail className="h-3.5 w-3.5" />,
    whatsapp: <MessageCircle className="h-3.5 w-3.5" />,
    sms: <MessageSquare className="h-3.5 w-3.5" />,
    call: <Phone className="h-3.5 w-3.5" />,
};
const CHILD_CHANNEL_COLOR: Record<string, string> = {
    email: "bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/20 dark:text-blue-400 dark:border-blue-800/40",
    whatsapp: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800/40",
    sms: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800/40",
    call: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-900/20 dark:text-violet-400 dark:border-violet-800/40",
};

function FollowupTimeline({ children }: { children: ChildInteraction[] }) {
    if (!children.length) return null;
    return (
        <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-3">Follow-ups ({children.length})</p>
            <div className="relative pl-4 space-y-3">
                <div className="absolute left-1.5 top-1 bottom-1 w-px bg-slate-200 dark:bg-slate-700" />
                {children.map(c => {
                    const ch = c.channel ?? "call";
                    const color = CHILD_CHANNEL_COLOR[ch] ?? CHILD_CHANNEL_COLOR.call;
                    const icon = CHILD_CHANNEL_ICON[ch] ?? <Phone className="h-3.5 w-3.5" />;
                    const ts = c.created_at ? new Date(c.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
                    return (
                        <div key={c.id} className={clsx("relative flex items-start gap-3 rounded-xl border p-3", color)}>
                            <div className="absolute -left-[11px] top-4 h-2 w-2 rounded-full bg-slate-300 dark:bg-slate-600 ring-2 ring-white dark:ring-slate-900" />
                            <div className="flex h-6 w-6 items-center justify-center rounded-lg flex-shrink-0 bg-white/60 dark:bg-black/20">
                                {icon}
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs font-semibold capitalize">{ch}</span>
                                    {c.direction && (
                                        <span className="text-[10px] opacity-70">{c.direction === "outbound" ? "↗" : "↙"} {c.direction}</span>
                                    )}
                                    <span className="text-[10px] opacity-60 ml-auto">{ts}</span>
                                </div>
                                {c.content && (
                                    <p className="mt-0.5 text-[11px] opacity-80 truncate">{c.content}</p>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function RawDataModal({ call, onClose }: { call: Interaction; onClose: () => void }) {
    const [copied, setCopied] = useState(false);
    const json = JSON.stringify(call.metadata_json, null, 2);

    const handleCopy = () => {
        navigator.clipboard.writeText(json).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
        });
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
            onClick={onClose}
        >
            <div
                className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 flex-shrink-0">
                    <div className="flex items-center gap-2">
                        <Code2 className="h-4 w-4 text-violet-400" />
                        <span className="text-sm font-semibold text-slate-100">Raw Call Data</span>
                        <span className="text-xs text-slate-500 font-mono ml-1">#{call.id}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleCopy}
                            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-semibold border border-slate-700 text-slate-300 hover:bg-slate-800 transition"
                        >
                            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                            {copied ? "Copied" : "Copy"}
                        </button>
                        <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition">
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>
                {/* JSON body */}
                <div className="flex-1 overflow-y-auto p-5">
                    <pre className="text-xs text-slate-300 font-mono leading-relaxed whitespace-pre-wrap break-all">
                        {json}
                    </pre>
                </div>
            </div>
        </div>
    );
}

// ── Types for Rio latency/tool data ─────────────────────────────────────
interface LatencyTurn {
    latency?: number;
    words?: string;
    prompt_tokens?: number;
    completion_tokens?: number;
    characters?: number;
    model?: string;
}
interface LatencySection {
    turns?: LatencyTurn[];
    p50?: number;
    p90?: number;
    p99?: number;
}
interface ToolCallLog {
    name?: string;
    arguments?: Record<string, unknown>;
    result?: unknown;
    latency?: number;
    turn_index?: number;
}
interface RioData {
    execution_id?: string;
    usage_breakdown?: { audio_duration?: number; input_tokens?: number; output_tokens?: number; total_cost?: number };
    cost_breakdown?: Record<string, unknown>;
    latency_data?: { transcriber?: LatencySection; llm?: LatencySection; synthesizer?: LatencySection };
    tool_call_logs?: ToolCallLog[];
    extracted_data?: Record<string, unknown>;
    to_number?: string;
    duration?: number;
}

function ms(s?: number) {
    if (s == null) return null;
    return s >= 1 ? `${s.toFixed(2)}s` : `${Math.round(s * 1000)}ms`;
}

function CallLogModal({ call, onClose }: { call: Interaction; onClose: () => void }) {
    const rio: RioData | null = (call.metadata_json as Record<string, unknown>)?.rio as RioData ?? null;
    if (!rio) return null;

    const stt = rio.latency_data?.transcriber?.turns ?? [];
    const llm = rio.latency_data?.llm?.turns ?? [];
    const tts = rio.latency_data?.synthesizer?.turns ?? [];
    const tools = rio.tool_call_logs ?? [];
    const turnCount = Math.max(stt.length, llm.length, tts.length);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
            <div className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 flex-shrink-0">
                    <div className="flex items-center gap-2">
                        <Activity className="h-4 w-4 text-violet-400" />
                        <span className="text-sm font-semibold text-slate-100">Call Log</span>
                        <span className="text-xs text-slate-500 font-mono ml-1">#{call.id}</span>
                        {rio.execution_id && (
                            <span className="text-[10px] text-slate-600 font-mono">{rio.execution_id.slice(0, 8)}…</span>
                        )}
                    </div>
                    <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition">
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-5 space-y-5">
                    {/* Usage summary */}
                    {rio.usage_breakdown && (
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            {[
                                { label: "Audio", value: rio.usage_breakdown.audio_duration != null ? `${rio.usage_breakdown.audio_duration.toFixed(0)}s` : null },
                                { label: "Input tokens", value: rio.usage_breakdown.input_tokens?.toLocaleString() },
                                { label: "Output tokens", value: rio.usage_breakdown.output_tokens?.toLocaleString() },
                                { label: "Cost", value: rio.usage_breakdown.total_cost != null ? `$${rio.usage_breakdown.total_cost.toFixed(4)}` : null },
                            ].filter(x => x.value != null).map(x => (
                                <div key={x.label} className="rounded-xl bg-slate-900 border border-slate-800 p-3 text-center">
                                    <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">{x.label}</p>
                                    <p className="text-sm font-bold text-slate-100">{x.value}</p>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Latency p50 pills */}
                    {rio.latency_data && (
                        <div className="flex flex-wrap gap-2">
                            {[
                                { label: "STT p50", value: ms(rio.latency_data.transcriber?.p50), color: "text-sky-400" },
                                { label: "LLM p50", value: ms(rio.latency_data.llm?.p50), color: "text-violet-400" },
                                { label: "TTS p50", value: ms(rio.latency_data.synthesizer?.p50), color: "text-emerald-400" },
                            ].filter(x => x.value).map(x => (
                                <span key={x.label} className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-semibold">
                                    <Zap className={clsx("h-3 w-3", x.color)} />
                                    <span className="text-slate-400">{x.label}</span>
                                    <span className={x.color}>{x.value}</span>
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Per-turn timeline */}
                    {turnCount > 0 && (
                        <div>
                            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-3">Turn-by-turn flow</p>
                            <div className="space-y-3">
                                {Array.from({ length: turnCount }).map((_, i) => {
                                    const sttT = stt[i];
                                    const llmT = llm[i];
                                    const ttsT = tts[i];
                                    const turnTools = tools.filter(t => t.turn_index === i);
                                    return (
                                        <div key={i} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 space-y-2">
                                            <p className="text-[10px] font-bold text-slate-500 uppercase">Turn {i + 1}</p>
                                            <div className="flex flex-wrap gap-2 items-start">
                                                {/* STT */}
                                                {sttT && (
                                                    <div className="flex-1 min-w-[140px] rounded-lg bg-sky-950/50 border border-sky-900/50 px-3 py-2">
                                                        <div className="flex items-center gap-1.5 mb-1">
                                                            <Mic className="h-3 w-3 text-sky-400" />
                                                            <span className="text-[10px] font-bold text-sky-400 uppercase">STT</span>
                                                            {sttT.latency != null && <span className="text-[10px] text-sky-300 ml-auto">{ms(sttT.latency)}</span>}
                                                        </div>
                                                        {sttT.words && <p className="text-[11px] text-slate-300 leading-relaxed line-clamp-2">{sttT.words}</p>}
                                                    </div>
                                                )}
                                                {/* LLM */}
                                                {llmT && (
                                                    <div className="flex-1 min-w-[140px] rounded-lg bg-violet-950/50 border border-violet-900/50 px-3 py-2">
                                                        <div className="flex items-center gap-1.5 mb-1">
                                                            <Zap className="h-3 w-3 text-violet-400" />
                                                            <span className="text-[10px] font-bold text-violet-400 uppercase">LLM</span>
                                                            {llmT.latency != null && <span className="text-[10px] text-violet-300 ml-auto">{ms(llmT.latency)}</span>}
                                                        </div>
                                                        <div className="flex gap-2 text-[10px] text-slate-400">
                                                            {llmT.prompt_tokens != null && <span>{llmT.prompt_tokens} in</span>}
                                                            {llmT.completion_tokens != null && <span>{llmT.completion_tokens} out</span>}
                                                        </div>
                                                    </div>
                                                )}
                                                {/* TTS */}
                                                {ttsT && (
                                                    <div className="flex-1 min-w-[140px] rounded-lg bg-emerald-950/50 border border-emerald-900/50 px-3 py-2">
                                                        <div className="flex items-center gap-1.5 mb-1">
                                                            <Phone className="h-3 w-3 text-emerald-400" />
                                                            <span className="text-[10px] font-bold text-emerald-400 uppercase">TTS</span>
                                                            {ttsT.latency != null && <span className="text-[10px] text-emerald-300 ml-auto">{ms(ttsT.latency)}</span>}
                                                        </div>
                                                        {ttsT.characters != null && <p className="text-[10px] text-slate-400">{ttsT.characters} chars</p>}
                                                    </div>
                                                )}
                                            </div>
                                            {/* Tool calls in this turn */}
                                            {turnTools.map((tc, j) => (
                                                <div key={j} className="rounded-lg bg-amber-950/30 border border-amber-900/40 px-3 py-2">
                                                    <div className="flex items-center gap-1.5 mb-1">
                                                        <Wrench className="h-3 w-3 text-amber-400" />
                                                        <span className="text-[10px] font-bold text-amber-400">{tc.name ?? "tool"}</span>
                                                        {tc.latency != null && <span className="text-[10px] text-amber-300 ml-auto">{ms(tc.latency)}</span>}
                                                    </div>
                                                    {tc.arguments && (
                                                        <p className="text-[10px] text-slate-400 font-mono truncate">
                                                            {JSON.stringify(tc.arguments)}
                                                        </p>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Orphan tool calls (no turn_index) */}
                    {tools.filter(t => t.turn_index == null).length > 0 && (
                        <div>
                            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-3">Tool calls</p>
                            <div className="space-y-2">
                                {tools.filter(t => t.turn_index == null).map((tc, j) => (
                                    <div key={j} className="rounded-lg bg-amber-950/30 border border-amber-900/40 px-3 py-2">
                                        <div className="flex items-center gap-1.5 mb-1">
                                            <Wrench className="h-3 w-3 text-amber-400" />
                                            <span className="text-[10px] font-bold text-amber-400">{tc.name ?? "tool"}</span>
                                            {tc.latency != null && <span className="text-[10px] text-amber-300 ml-auto">{ms(tc.latency)}</span>}
                                        </div>
                                        {tc.arguments && (
                                            <p className="text-[10px] text-slate-400 font-mono truncate">{JSON.stringify(tc.arguments)}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Extracted data */}
                    {rio.extracted_data && Object.keys(rio.extracted_data).length > 0 && (
                        <div>
                            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-3">Extracted data</p>
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                {Object.entries(rio.extracted_data).map(([k, v]) => (
                                    <div key={k} className="rounded-lg bg-slate-900 border border-slate-800 px-3 py-2">
                                        <p className="text-[10px] text-slate-500 capitalize mb-0.5">{k.replace(/_/g, " ")}</p>
                                        <p className="text-xs text-slate-200 font-medium truncate">{String(v)}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function CallDetailModal({ call, onClose }: { call: Interaction; onClose: () => void }) {
    const isOutbound = call.direction === "outbound";
    const children = call.children ?? [];
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            onClick={onClose}
        >
            <div
                className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Modal header */}
                <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-900">
                    <div className="flex items-center gap-3 min-w-0">
                        <div className={clsx("flex h-9 w-9 items-center justify-center rounded-xl flex-shrink-0", typeColor(call.type))}>
                            {typeIcon(call.type)}
                        </div>
                        <div className="min-w-0">
                            <p className="font-bold text-slate-900 dark:text-slate-100 truncate">{callTitle(call)}</p>
                            <p className="text-xs text-slate-400">{formatDate(call)}</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                        {isOutbound
                            ? <span className="flex items-center gap-1 rounded-full bg-violet-100 px-2.5 py-1 text-[10px] font-semibold text-violet-700 dark:bg-violet-900/30 dark:text-violet-300"><ArrowUpRight className="h-3 w-3" />Outbound</span>
                            : <span className="flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"><ArrowDownLeft className="h-3 w-3" />Inbound</span>
                        }
                        {statusBadge(call.status)}
                        <button onClick={onClose} className="ml-1 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 cursor-pointer">
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                {/* Meta row */}
                <div className="flex flex-wrap gap-4 border-b border-slate-100 px-6 py-3 dark:border-slate-800 text-xs text-slate-500">
                    {formatDuration(call.recording_duration) && (
                        <span className="flex items-center gap-1"><Clock className="h-3.5 w-3.5" />{formatDuration(call.recording_duration)}</span>
                    )}
                    {call.channel && <span>Channel: <span className="font-medium text-slate-700 dark:text-slate-300">{call.channel}</span></span>}
                    <span>ID: <span className="font-mono text-slate-700 dark:text-slate-300">#{call.id}</span></span>
                    {call.source && (
                        <span>Provider: <span className="font-medium text-slate-700 dark:text-slate-300 uppercase">{call.source}</span></span>
                    )}
                    {call.delivery_status && (
                        <span>Delivery: <span className="font-medium text-violet-600 dark:text-violet-400">{call.delivery_status}</span></span>
                    )}
                    {call.eval_score != null && (
                        <span>AI Eval: <span className={clsx("font-bold", call.eval_passed ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                            {Math.round((call.eval_score / 5) * 100)}% {call.eval_passed ? "✓" : "✗"}
                        </span></span>
                    )}
                    {call.csat_rating != null && (
                        <span>CSAT: <span className="font-medium text-amber-500">{"★".repeat(call.csat_rating)}{"☆".repeat(5 - call.csat_rating)} ({call.csat_rating}/5)</span></span>
                    )}
                </div>

                {/* Body */}
                <div className="p-6 space-y-5">
                    {call.transcript || call.recording_url ? (
                        <WaveformPlayer
                            interactionId={call.id}
                            recordingUrl={call.recording_url ?? undefined}
                            transcript={call.transcript}
                            duration={call.recording_duration}
                        />
                    ) : call.content ? (
                        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/60">
                            <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">{call.content}</p>
                        </div>
                    ) : (
                        <p className="text-sm text-slate-400 text-center py-6">No transcript or recording available.</p>
                    )}

                    {call.type === "call" && <CallEvalPanel interactionId={call.id} />}

                    {children.length > 0 && (
                        <div className="border-t border-slate-100 dark:border-slate-800 pt-5">
                            <FollowupTimeline children={children} />
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default function CallsPage() {
    const { user, sessionTimeout } = useAuth();
    const qc = useQueryClient();
    const [selectedCall, setSelectedCall] = useState<Interaction | null>(null);
    const [rawDataCall, setRawDataCall] = useState<Interaction | null>(null);
    const [logCall, setLogCall] = useState<Interaction | null>(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [itemsPerPage] = useState(20);
    const [dialLimit, setDialLimit] = useState(10);
    const [directionFilter, setDirectionFilter] = useState<"" | "outbound" | "inbound">("");

    const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");
    const CRM_BASE = `${API_BASE}/crm`;

    type CallsPayload = { items: Interaction[]; total: number };
    const callsQuery = useQuery<CallsPayload>({
        queryKey: ["calls", currentPage, itemsPerPage, directionFilter],
        enabled: !!user,
        refetchInterval: 30_000,
        queryFn: async () => {
            const params = new URLSearchParams({ page: String(currentPage), limit: String(itemsPerPage), type: "call" });
            if (directionFilter) params.set("direction", directionFilter);
            const res = await apiFetch(`${CRM_BASE}/interactions?${params}`);
            if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            return res.json();
        },
    });

    const calls = callsQuery.data?.items ?? [];
    const totalCalls = callsQuery.data?.total ?? 0;
    const loading = callsQuery.isLoading;
    const error = callsQuery.error ? (callsQuery.error instanceof Error ? callsQuery.error.message : "Failed to load") : null;
    const totalPages = Math.ceil(totalCalls / itemsPerPage);

    const dialerMutation = useMutation<DialerResult, Error, void>({
        mutationFn: async () => {
            const res = await apiFetch(`${API_BASE}/call-tasks/run-batch?limit=${dialLimit}`, { method: "POST" });
            if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body.detail || `Server ${res.status}`);
            }
            return res.json();
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: ["calls"] }),
    });

    const dialerRunning = dialerMutation.isPending;
    const dialerResult = dialerMutation.data ?? null;
    const dialerError = dialerMutation.error ? dialerMutation.error.message : null;

    return (
        <div className="space-y-6 pb-8">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-4xl font-bold tracking-tight">
                        <span className="gradient-text">Call History</span>
                    </h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium flex items-center gap-2">
                        Voice calls only
                        {!loading && totalCalls > 0 && (
                            <span className="rounded-full bg-violet-100 dark:bg-violet-900/30 px-2.5 py-0.5 text-xs font-bold text-violet-700 dark:text-violet-300">
                                {totalCalls} total
                            </span>
                        )}
                    </p>
                </div>
                {/* Direction filter */}
                <div className="flex items-center gap-1 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1 self-start mt-1">
                    {(["", "outbound", "inbound"] as const).map(d => (
                        <button
                            key={d}
                            onClick={() => { setDirectionFilter(d); setCurrentPage(1); }}
                            className={clsx(
                                "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer",
                                directionFilter === d
                                    ? "bg-violet-600 text-white shadow"
                                    : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                            )}
                        >
                            {d === "" ? "All" : d === "outbound" ? "↗ Outbound" : "↙ Inbound"}
                        </button>
                    ))}
                </div>
            </div>

            {/* Batch Dialer */}
            <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Batch dialer</h2>
                        <p className="text-sm text-slate-500 dark:text-slate-400">Run queued call tasks for all leads in sequence.</p>
                    </div>
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                            <label className="font-medium">Limit</label>
                            <input
                                type="number"
                                value={dialLimit}
                                onChange={(e) => setDialLimit(Math.max(1, Math.min(100, Number(e.target.value))))}
                                className="w-16 rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                                min={1} max={100}
                            />
                        </div>
                        <button
                            onClick={() => dialerMutation.mutate()}
                            disabled={dialerRunning}
                            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60 cursor-pointer"
                        >
                            {dialerRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
                            {dialerRunning ? "Dialing..." : "Run batch"}
                        </button>
                    </div>
                </div>

                {dialerError && (
                    <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
                        {dialerError}
                    </div>
                )}
                {dialerResult && (
                    <div className="mt-4 space-y-2">
                        <div className="flex gap-4 text-sm font-medium text-slate-700 dark:text-slate-200">
                            <span className="text-emerald-600 dark:text-emerald-400">Attempted: {dialerResult.attempted ?? dialerResult.results?.length ?? 0}</span>
                            <span className="text-amber-600 dark:text-amber-400">Skipped: {dialerResult.skipped ?? 0}</span>
                        </div>
                        {Array.isArray(dialerResult.results) && dialerResult.results.length > 0 && (
                            <div className="max-h-40 overflow-y-auto space-y-1 rounded-xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-slate-900/40">
                                {dialerResult.results.map((r, i) => (
                                    <div key={i} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                                        <span className={`h-2 w-2 rounded-full flex-shrink-0 ${r.status === "dialing" || r.status === "initiated" ? "bg-emerald-500" : r.status === "skipped" ? "bg-amber-400" : "bg-red-400"}`} />
                                        Task #{r.task_id} — {r.status}{r.reason ? ` (${r.reason})` : ""}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {error && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-500/30 dark:bg-red-500/10">
                    <p className="text-sm text-red-700 dark:text-red-400 font-medium">⚠️ {error}</p>
                </div>
            )}

            {/* Table */}
            {loading ? (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
                    <div className="h-12 bg-slate-50/80 dark:bg-slate-800/40 border-b border-slate-100 dark:border-slate-800" />
                    {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="h-14 border-b border-slate-100 dark:border-slate-800/60 animate-pulse bg-slate-50/30 dark:bg-slate-800/20" style={{ opacity: 1 - i * 0.1 }} />
                    ))}
                </div>
            ) : calls.length === 0 ? (
                <div className="rounded-2xl glass p-12 border border-white/40 dark:border-white/10 text-center">
                    <div className="relative mx-auto mb-6 flex h-24 w-24 items-center justify-center">
                        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-violet-500 to-blue-500 opacity-20 animate-ping" />
                        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50">
                            <Phone className="h-8 w-8 text-white" />
                        </div>
                    </div>
                    <h3 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">No calls recorded yet</h3>
                    <p className="text-slate-600 dark:text-slate-400 max-w-md mx-auto">
                        Start calling your leads from the dashboard to see detailed call logs here.
                    </p>
                </div>
            ) : (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/40">
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 w-10" />
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400">Lead</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400">Direction</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden sm:table-cell">Date & Time</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden md:table-cell">Duration</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden md:table-cell">Status</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden lg:table-cell">Provider</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden lg:table-cell">Feedback</th>
                                <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-slate-400 w-10 hidden md:table-cell">Rec</th>
                                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-slate-400 hidden lg:table-cell">Follow-ups</th>
                                <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-slate-400 w-14 hidden lg:table-cell">Raw</th>
                                <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-slate-400 w-14 hidden lg:table-cell">Logs</th>
                            </tr>
                        </thead>
                        <tbody>
                            {calls.map((call, i) => {
                                const isOutbound = call.direction === "outbound";
                                const hasRecording = !!call.recording_url || !!call.transcript;
                                return (
                                    <tr
                                        key={call.id}
                                        onClick={() => setSelectedCall(call)}
                                        className={clsx(
                                            "cursor-pointer border-b border-slate-100 dark:border-slate-800/60 transition-colors",
                                            "hover:bg-violet-50/60 dark:hover:bg-violet-900/10",
                                            i % 2 === 0 ? "bg-white/40 dark:bg-slate-900/20" : "bg-slate-50/30 dark:bg-slate-800/10"
                                        )}
                                    >
                                        {/* Type icon */}
                                        <td className="px-4 py-3">
                                            <div className={clsx("flex h-8 w-8 items-center justify-center rounded-lg flex-shrink-0", typeColor(call.type))}>
                                                {typeIcon(call.type)}
                                            </div>
                                        </td>

                                        {/* Lead name */}
                                        <td className="px-4 py-3">
                                            <p className="font-semibold text-slate-900 dark:text-slate-100 truncate max-w-[180px]">
                                                {callTitle(call)}
                                            </p>
                                            {/* Show date inline on xs-only (below sm) */}
                                            <p className="text-[11px] text-slate-400 sm:hidden">{formatDate(call)}</p>
                                        </td>

                                        {/* Direction */}
                                        <td className="px-4 py-3">
                                            {isOutbound
                                                ? <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 dark:bg-violet-900/30 px-2.5 py-1 text-[10px] font-semibold text-violet-700 dark:text-violet-300"><ArrowUpRight className="h-3 w-3" />Outbound</span>
                                                : <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300"><ArrowDownLeft className="h-3 w-3" />Inbound</span>
                                            }
                                        </td>

                                        {/* Date & Time */}
                                        <td className="px-4 py-3 hidden sm:table-cell">
                                            <div className="text-[11px] text-slate-700 dark:text-slate-300 font-medium whitespace-nowrap">
                                                {formatDate(call)}
                                            </div>
                                        </td>

                                        {/* Duration */}
                                        <td className="px-4 py-3 hidden md:table-cell">
                                            {formatDuration(call.recording_duration)
                                                ? <span className="flex items-center gap-1 text-[11px] font-mono text-slate-600 dark:text-slate-300"><Clock className="h-3 w-3 text-slate-400" />{formatDuration(call.recording_duration)}</span>
                                                : <span className="text-slate-300 dark:text-slate-600">—</span>
                                            }
                                        </td>

                                        {/* Status */}
                                        <td className="px-4 py-3 hidden md:table-cell">
                                            {statusBadge(call.status) ?? <span className="text-slate-300 dark:text-slate-600">—</span>}
                                        </td>

                                        {/* Provider */}
                                        <td className="px-4 py-3 hidden lg:table-cell">
                                            {providerBadge(call.source)}
                                        </td>

                                        {/* Feedback (AI eval + CSAT) */}
                                        <td className="px-4 py-3 hidden lg:table-cell">
                                            <FeedbackCell call={call} />
                                        </td>

                                        {/* Recording indicator */}
                                        <td className="px-4 py-3 text-center hidden md:table-cell">
                                            {hasRecording
                                                ? <Mic className="h-3.5 w-3.5 text-violet-500 mx-auto" />
                                                : <MicOff className="h-3.5 w-3.5 text-slate-300 dark:text-slate-700 mx-auto" />
                                            }
                                        </td>

                                        {/* Follow-up channel badges */}
                                        <td className="px-4 py-3 hidden lg:table-cell">
                                            {(call.children ?? []).length > 0 ? (
                                                <div className="flex flex-wrap gap-1">
                                                    {Array.from(new Set((call.children ?? []).map(c => c.channel ?? "call"))).map(ch => (
                                                        <span key={ch} className={clsx(
                                                            "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                                                            CHILD_CHANNEL_COLOR[ch] ?? "bg-slate-100 text-slate-500 border-slate-200"
                                                        )}>
                                                            {CHILD_CHANNEL_ICON[ch] ?? <Phone className="h-3 w-3" />}
                                                            {ch}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : (
                                                <span className="text-slate-300 dark:text-slate-700 text-[11px]">—</span>
                                            )}
                                        </td>

                                        {/* Raw data button */}
                                        <td className="px-4 py-3 text-center hidden lg:table-cell" onClick={(e) => e.stopPropagation()}>
                                            {call.metadata_json ? (
                                                <button
                                                    onClick={() => setRawDataCall(call)}
                                                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2 py-1 text-[10px] font-semibold text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition"
                                                >
                                                    <Code2 className="h-3 w-3" />
                                                    JSON
                                                </button>
                                            ) : (
                                                <span className="text-slate-300 dark:text-slate-700">—</span>
                                            )}
                                        </td>

                                        {/* Logs (Rio timeline) button */}
                                        <td className="px-4 py-3 text-center hidden lg:table-cell" onClick={(e) => e.stopPropagation()}>
                                            {(call.metadata_json as Record<string, unknown>)?.rio ? (
                                                <button
                                                    onClick={() => setLogCall(call)}
                                                    className="inline-flex items-center gap-1 rounded-lg border border-violet-300 dark:border-violet-800 px-2 py-1 text-[10px] font-semibold text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition"
                                                >
                                                    <Activity className="h-3 w-3" />
                                                    Logs
                                                </button>
                                            ) : (
                                                <span className="text-slate-300 dark:text-slate-700">—</span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="flex items-center justify-between border-t border-slate-100 dark:border-slate-800 px-4 py-3 bg-slate-50/80 dark:bg-slate-800/40">
                            <p className="text-xs text-slate-400">
                                {(currentPage - 1) * itemsPerPage + 1}–{Math.min(currentPage * itemsPerPage, totalCalls)} of {totalCalls}
                            </p>
                            <div className="flex items-center gap-1">
                                <button
                                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                    disabled={currentPage === 1}
                                    className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30 cursor-pointer"
                                >
                                    <ChevronLeft className="h-4 w-4" />
                                </button>
                                <span className="px-2 text-xs font-medium text-slate-600 dark:text-slate-300">{currentPage} / {totalPages}</span>
                                <button
                                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                    disabled={currentPage === totalPages}
                                    className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30 cursor-pointer"
                                >
                                    <ChevronRight className="h-4 w-4" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Detail modal */}
            {selectedCall && (
                <CallDetailModal call={selectedCall} onClose={() => setSelectedCall(null)} />
            )}

            {/* Raw data modal */}
            {rawDataCall && (
                <RawDataModal call={rawDataCall} onClose={() => setRawDataCall(null)} />
            )}

            {/* Call log timeline modal */}
            {logCall && (
                <CallLogModal call={logCall} onClose={() => setLogCall(null)} />
            )}
        </div>
    );
}
