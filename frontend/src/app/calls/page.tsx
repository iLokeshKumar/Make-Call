"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { Phone, Clock, CheckCircle, ChevronDown, ChevronUp, MessageSquare, Mail, MessageCircle, PlayCircle, Loader2 } from "lucide-react";
import clsx from "clsx";
import Pagination from "@/components/Pagination";

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
}

interface DialerResult {
    attempted: number;
    skipped: number;
    results: Array<{ task_id: number; status: string; reason?: string }>;
}

export default function CallsPage() {
    const [calls, setCalls] = useState<Interaction[]>([]);
    const { token, sessionTimeout } = useAuth();
    const [loading, setLoading] = useState(true);
    const [expandedCall, setExpandedCall] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);

    // Pagination State
    const [currentPage, setCurrentPage] = useState(1);
    const [totalCalls, setTotalCalls] = useState(0);
    const [itemsPerPage] = useState(10);
    const totalPages = Math.ceil(totalCalls / itemsPerPage);

    // Batch dialer state
    const [dialLimit, setDialLimit] = useState(10);
    const [dialerRunning, setDialerRunning] = useState(false);
    const [dialerResult, setDialerResult] = useState<DialerResult | null>(null);
    const [dialerError, setDialerError] = useState<string | null>(null);

    const API_BASE = "http://localhost:6060";
    const CRM_BASE = `${API_BASE}/crm`;

    const fetchCalls = useCallback(async (page: number = 1) => {
        setLoading(true);
        try {
            const res = await fetch(`${CRM_BASE}/interactions?page=${page}&limit=${itemsPerPage}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });
            if (res.status === 401) {
                sessionTimeout();
                return;
            }
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            const data = await res.json();
            
            setCalls(data.items || []);
            setTotalCalls(data.total || 0);
            // Don't reset currentPage from the response — the backend doesn't return it, so `data.page || 1` always snapped back to page 1 and thrashed useEffect into re-fetching page 1 right after every page change.
            setError(null);
        } catch (err: any) {
            console.error("Failed to fetch calls:", err);
            setError(err.message || "Could not connect to backend");
        } finally {
            setLoading(false);
        }
    }, [token, itemsPerPage, sessionTimeout]);

    useEffect(() => {
        fetchCalls(currentPage);
    }, [fetchCalls, currentPage]);

    async function handleRunBatch() {
        if (!token) return;
        setDialerRunning(true);
        setDialerResult(null);
        setDialerError(null);
        try {
            const res = await fetch(`${API_BASE}/call-tasks/run-batch?limit=${dialLimit}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.status === 401) { sessionTimeout(); return; }
            if (!res.ok) throw new Error((await res.json()).detail || `Server ${res.status}`);
            setDialerResult(await res.json());
            fetchCalls(currentPage);
        } catch (e) {
            setDialerError(e instanceof Error ? e.message : "Batch dial failed");
        } finally {
            setDialerRunning(false);
        }
    }

    const toggleExpand = (id: number) => {
        setExpandedCall(expandedCall === id ? null : id);
    };

    const getInteractionIcon = (type: string) => {
        const lowerType = type.toLowerCase();
        if (lowerType.includes("email")) return <Mail className="h-5 w-5" />;
        if (lowerType.includes("whatsapp")) return <MessageCircle className="h-5 w-5" />;
        if (lowerType.includes("multi-channel")) return <MessageSquare className="h-5 w-5" />;
        return <Phone className="h-5 w-5" />;
    };

    const getInteractionColor = (type: string) => {
        const lowerType = type.toLowerCase();
        if (lowerType.includes("email")) return "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400";
        if (lowerType.includes("whatsapp")) return "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400";
        if (lowerType.includes("multi-channel")) return "bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400";
        return "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400";
    };

    const TYPE_LABELS: Record<string, string> = {
        call: "Voice Call",
        call_completed: "Call Ended",
        call_summary: "Call Summary",
        whatsapp: "WhatsApp Message",
        email: "Email",
        sms: "SMS",
    };

    const getInteractionTitle = (call: Interaction) => {
        if (call.type === "call") {
            const isOutbound = call.direction === "outbound" || (call.content || "").includes("Outbound");
            if (isOutbound) return call.lead_name ? `Outbound to ${call.lead_name}` : "Outbound Call";
            return call.lead_name ? `Inbound from ${call.lead_name}` : "Inbound Call";
        }
        if (call.type === "call_completed" && call.lead_name) return `Call ended — ${call.lead_name}`;
        if (call.type === "call_summary" && call.lead_name) return `Call summary — ${call.lead_name}`;
        return TYPE_LABELS[call.type] || call.type;
    };

    const formatDuration = (seconds?: number | null) => {
        if (!seconds || seconds <= 0) return null;
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return m > 0 ? `${m}m ${s}s` : `${s}s`;
    };

    const truncate = (text: string, max = 140) => (text.length > max ? text.slice(0, max).trimEnd() + "…" : text);

    return (
        <div className="space-y-6 pb-8">
            {/* Header */}
            <div>
                <h1 className="text-4xl font-bold tracking-tight">
                    <span className="gradient-text">Call History</span>
                </h1>
                <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
                    Track and analyze your AI voice interactions
                </p>
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
                            onClick={handleRunBatch}
                            disabled={dialerRunning}
                            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
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
                    <p className="text-sm text-red-700 dark:text-red-400 font-medium">
                        ⚠️ {error}. Please ensure the backend server is running at http://localhost:6060
                    </p>
                </div>
            )}

            {loading ? (
                <div className="space-y-4">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="h-20 rounded-xl glass border border-white/20 dark:border-white/10 animate-pulse bg-slate-100/50 dark:bg-slate-800/50" />
                    ))}
                </div>
            ) : calls.length === 0 ? (
                /* Empty State */
                <div className="rounded-2xl glass p-12 border border-white/40 dark:border-white/10 text-center">
                    <div className="relative mx-auto mb-6 flex h-24 w-24 items-center justify-center">
                        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-violet-500 to-blue-500 opacity-20 animate-ping" />
                        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50">
                            <Phone className="h-8 w-8 text-white" />
                        </div>
                    </div>

                    <h3 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">No calls recorded yet</h3>
                    <p className="text-slate-600 dark:text-slate-400 mb-6 max-w-md mx-auto">
                        Start calling your leads from the dashboard to see detailed call logs here.
                    </p>
                </div>
            ) : (
                /* Calls List */
                <div className="space-y-4">
                    {calls.map((call) => (
                        <div key={call.id} className="rounded-xl overflow-hidden glass border border-white/40 dark:border-white/10 transition-all hover:shadow-lg">
                            <div
                                onClick={() => toggleExpand(call.id)}
                                className="p-4 flex items-center justify-between cursor-pointer"
                            >
                                <div className="flex items-center space-x-4 min-w-0 flex-1">
                                    <div className={clsx("flex h-10 w-10 items-center justify-center rounded-lg shadow-sm font-bold flex-shrink-0", getInteractionColor(call.type))}>
                                        {getInteractionIcon(call.type)}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <p className="font-semibold text-slate-900 dark:text-white">
                                                {getInteractionTitle(call)}
                                            </p>
                                            {formatDuration(call.recording_duration) && (
                                                <span className="text-[10px] font-mono text-slate-500 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                                                    {formatDuration(call.recording_duration)}
                                                </span>
                                            )}
                                            {call.status && call.status !== "active" && call.status !== "logged" && (
                                                <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                                                    {call.status}
                                                </span>
                                            )}
                                            {call.delivery_status && (
                                                <span className="text-[10px] font-medium uppercase tracking-wide text-violet-600 bg-violet-50 dark:bg-violet-900/30 dark:text-violet-300 px-1.5 py-0.5 rounded">
                                                    {call.delivery_status}
                                                </span>
                                            )}
                                        </div>
                                        {call.content && call.type !== "call" && (
                                            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300 truncate">
                                                {truncate(call.content)}
                                            </p>
                                        )}
                                        <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                                            {(() => {
                                                const ts = call.started_at ?? call.created_at ?? call.timestamp;
                                                if (!ts) return "Unknown";
                                                const date = new Date(ts);
                                                return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
                                            })()}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex items-center space-x-3">
                                    {(call.transcript || (call.type !== "call" && call.content)) && (
                                        <div className="h-2 w-2 rounded-full bg-violet-500 animate-pulse shadow-[0_0_8px_rgba(139,92,246,0.5)]" />
                                    )}
                                    {expandedCall === call.id ? <ChevronUp className="h-5 w-5 text-slate-400" /> : <ChevronDown className="h-5 w-5 text-slate-400" />}
                                </div>
                            </div>

                            {/* Expanded Section */}
                            {expandedCall === call.id && (
                                <div className="p-4 bg-slate-50/50 dark:bg-slate-900/50 border-t border-slate-100 dark:border-slate-800 animate-in slide-in-from-top-2 duration-300">
                                    <div className="flex items-center justify-between mb-3">
                                        <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                                            {call.type === 'call' ? 'Conversation Transcript' : 'Interaction Details'}
                                        </h4>
                                        <span className="text-[10px] bg-white/50 dark:bg-slate-800 px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 text-slate-500 font-mono">ID: #{call.id}</span>
                                    </div>
                                    
                                    {call.transcript ? (
                                        <div className="space-y-2">
                                            {call.transcript.split("\n").map((line, i) => {
                                                const isRio = line.startsWith("Rio:");
                                                const isSystem = line.startsWith("[System]:");
                                                return (
                                                    <div key={i} className={clsx(
                                                        "rounded-lg p-2.5 text-sm border shadow-sm",
                                                        isRio ? "bg-violet-50/80 dark:bg-violet-900/20 border-violet-100 dark:border-violet-800/50 text-violet-700 dark:text-violet-300 font-medium" :
                                                            isSystem ? "bg-slate-100/80 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700/50 text-slate-500 dark:text-slate-400 italic" :
                                                                "bg-white dark:bg-slate-800/80 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300"
                                                    )}>
                                                        <span className="font-mono text-[10px] opacity-40 mr-2">[{i + 1}]</span>
                                                        <span className="leading-relaxed">{line}</span>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    ) : (
                                        <div className="rounded-lg p-4 bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 shadow-sm">
                                            <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed font-medium">
                                                {call.content}
                                            </p>
                                            {call.type === 'call' && (
                                                <p className="mt-2 text-[10px] text-slate-400 italic font-medium">No detailed transcript available for this voice interaction.</p>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {!loading && totalCalls > 0 && (
                <div className="mt-8 rounded-2xl glass p-4 border border-white/40 dark:border-white/10">
                    <Pagination
                        currentPage={currentPage}
                        totalPages={totalPages}
                        onPageChange={(page) => setCurrentPage(page)}
                        totalItems={totalCalls}
                        itemsPerPage={itemsPerPage}
                    />
                </div>
            )}
        </div>
    );
}
