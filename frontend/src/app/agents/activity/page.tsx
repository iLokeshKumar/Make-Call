"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Activity, Mail, MessageCircle, Phone, UserCheck, Trophy, XCircle, AlertTriangle,
} from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { useAuth } from "@/context/AuthContext";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";
const WS_BASE = API_BASE.replace(/^http/, "ws");
const MAX_EVENTS = 100;
const PULSE_DURATION_MS = 2500;

const ISM_STAGES = [
  { key: "new",         label: "New",          cls: "border-slate-300  bg-slate-50   dark:border-slate-700 dark:bg-slate-900/30",         dot: "bg-slate-400" },
  { key: "contacted",   label: "Contacted",    cls: "border-blue-200   bg-blue-50    dark:border-blue-500/20 dark:bg-blue-500/5",         dot: "bg-blue-400" },
  { key: "engaged",     label: "Engaged",      cls: "border-violet-200 bg-violet-50  dark:border-violet-500/20 dark:bg-violet-500/5",     dot: "bg-violet-500" },
  { key: "quote_sent",  label: "Quote Sent",   cls: "border-amber-200  bg-amber-50   dark:border-amber-500/20 dark:bg-amber-500/5",       dot: "bg-amber-400" },
  { key: "negotiation", label: "Negotiation",  cls: "border-orange-200 bg-orange-50  dark:border-orange-500/20 dark:bg-orange-500/5",     dot: "bg-orange-400" },
  { key: "closed_won",  label: "Closed Won",   cls: "border-emerald-200 bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/5",  dot: "bg-emerald-500" },
  { key: "closed_lost", label: "Closed Lost",  cls: "border-red-200    bg-red-50     dark:border-red-500/20 dark:bg-red-500/5",           dot: "bg-red-400" },
] as const;

type StageKey = typeof ISM_STAGES[number]["key"];

type Lead = {
  id: number;
  name: string;
  ism_stage?: string | null;
  lead_score?: number | null;
};

type IsmEvent = {
  type: "ism_activity" | "ping";
  lead_id?: number | null;
  lead_name?: string | null;
  stage?: string | null;
  action?: string;
  reason?: string | null;
  metadata?: Record<string, unknown>;
  ts?: string;
};

const ACTION_META: Record<string, { label: string; tone: string; Icon: React.ComponentType<{ className?: string }> }> = {
  dispatched_email:    { label: "Email sent",     tone: "bg-blue-500/15 text-blue-700 dark:text-blue-300",       Icon: Mail },
  dispatched_whatsapp: { label: "WhatsApp sent",  tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300", Icon: MessageCircle },
  dispatched_call:     { label: "Call queued",    tone: "bg-violet-500/15 text-violet-700 dark:text-violet-300", Icon: Phone },
  handoff:             { label: "Handoff",        tone: "bg-amber-500/15 text-amber-700 dark:text-amber-300",   Icon: UserCheck },
  auto_closed_won:     { label: "Auto-Won",       tone: "bg-emerald-600/20 text-emerald-700 dark:text-emerald-300", Icon: Trophy },
  auto_closed_lost:    { label: "Auto-Lost",      tone: "bg-slate-500/15 text-slate-700 dark:text-slate-300",   Icon: XCircle },
  dispatch_failed:     { label: "Dispatch error", tone: "bg-red-500/15 text-red-700 dark:text-red-300",         Icon: AlertTriangle },
};

function actionMeta(action: string | undefined) {
  if (!action) return { label: "Activity", tone: "bg-slate-500/15 text-slate-700", Icon: Activity };
  return ACTION_META[action] ?? { label: action, tone: "bg-slate-500/15 text-slate-700 dark:text-slate-300", Icon: Activity };
}

function formatTime(iso?: string) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

function ScoreDot({ score }: { score?: number | null }) {
  if (score == null) return null;
  const s = Math.round(score);
  const cls = s >= 70 ? "bg-emerald-400" : s >= 40 ? "bg-amber-400" : "bg-slate-300";
  return <span title={`ICP ${s}`} className={`inline-block h-2 w-2 rounded-full ${cls}`} />;
}

export default function IsmActivityPage() {
  const { user, sessionTimeout } = useAuth();
  const [events, setEvents] = useState<IsmEvent[]>([]);
  const [connected, setConnected] = useState(false);
  // lead_id → expiry timestamp for the pulse highlight
  const [pulses, setPulses] = useState<Record<number, number>>({});
  const wsRef = useRef<WebSocket | null>(null);

  // Lead pipeline data — same shape as /leads/kanban.  Polled every 30s
  // (the WS feed handles the high-frequency activity; pipeline state changes
  // less often).
  const leadsQuery = useQuery<{ items: Lead[] }>({
    queryKey: ["activity-kanban-leads"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=500`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load leads");
      return res.json();
    },
  });
  const leads = leadsQuery.data?.items ?? [];

  // Group leads by stage for the kanban columns
  const leadsByStage = useMemo(() => {
    const acc: Record<string, Lead[]> = {};
    for (const s of ISM_STAGES) acc[s.key] = [];
    for (const l of leads) {
      const k = (l.ism_stage || "new") as string;
      if (acc[k]) acc[k].push(l);
    }
    return acc;
  }, [leads]);

  // WebSocket — append to feed AND trigger pulse on the matching lead card
  useEffect(() => {
    if (!user?.company_id) return;
    const url = `${WS_BASE}/ws/ism-activity/${user.company_id}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as IsmEvent;
        if (msg.type !== "ism_activity") return;
        setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
        if (msg.lead_id) {
          const expiry = Date.now() + PULSE_DURATION_MS;
          setPulses((prev) => ({ ...prev, [msg.lead_id as number]: expiry }));
        }
      } catch {
        // ignore
      }
    };
    return () => { ws.close(); };
  }, [user?.company_id]);

  // Sweep expired pulses every 500ms
  useEffect(() => {
    const t = setInterval(() => {
      const now = Date.now();
      setPulses((prev) => {
        const next: Record<number, number> = {};
        let changed = false;
        for (const [k, v] of Object.entries(prev)) {
          if (v > now) next[Number(k)] = v;
          else changed = true;
        }
        return changed ? next : prev;
      });
    }, 500);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6 pb-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/agents/approvals" className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-violet-600 dark:text-violet-300">
            <ArrowLeft className="h-4 w-4" /> Approvals
          </Link>
          <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            <Activity className="h-7 w-7 text-violet-500" /> Agent Activity
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Pipeline state above, live decisions below. Cards pulse when the agent acts on them.
          </p>
        </div>
        <Badge variant={connected ? "default" : "outline"} className={connected ? "bg-emerald-600 text-white" : ""}>
          {connected ? "● Live" : "○ Disconnected"}
        </Badge>
      </div>

      {/* Kanban — pipeline state */}
      <div className="overflow-x-auto">
        <div className="flex gap-3 min-w-max pb-2">
          {ISM_STAGES.map((s) => {
            const stageLeads = leadsByStage[s.key] || [];
            return (
              <div
                key={s.key}
                className={`min-w-[220px] rounded-2xl border p-3 ${s.cls}`}
              >
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${s.dot}`} />
                    <span className="text-xs font-semibold uppercase tracking-widest text-slate-700 dark:text-slate-300">
                      {s.label}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500">{stageLeads.length}</span>
                </div>
                <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                  {stageLeads.length === 0 && (
                    <p className="text-[11px] text-slate-400 italic">empty</p>
                  )}
                  {stageLeads.slice(0, 30).map((l) => {
                    const isPulsing = !!pulses[l.id];
                    return (
                      <Link
                        key={l.id}
                        href={`/leads/${l.id}`}
                        className={`block rounded-lg border bg-white/80 px-2 py-1.5 text-[11px] transition-all dark:bg-slate-900/60 ${
                          isPulsing
                            ? "border-violet-500 ring-2 ring-violet-400 ring-offset-1 shadow-md scale-[1.02]"
                            : "border-slate-200 hover:border-slate-300 dark:border-white/10"
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="flex-1 truncate font-medium text-slate-900 dark:text-white">
                            {l.name}
                          </span>
                          <ScoreDot score={l.lead_score} />
                        </div>
                      </Link>
                    );
                  })}
                  {stageLeads.length > 30 && (
                    <p className="text-[10px] text-slate-400 italic">+{stageLeads.length - 30} more</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Feed — live decisions */}
      <Card className="border-slate-200 dark:border-white/10">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-900 dark:text-white">
            Recent activity {events.length > 0 && <span className="text-xs font-normal text-slate-500">· {events.length}</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center dark:border-white/10">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">No agent activity yet</p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Run a worker cycle — events appear here as the agent dispatches, hands off, or auto-closes leads.
              </p>
            </div>
          ) : (
            <ol className="space-y-2">
              {events.map((ev, idx) => {
                const m = actionMeta(ev.action);
                const Icon = m.Icon;
                return (
                  <li
                    key={`${ev.ts}-${idx}`}
                    className="flex items-start gap-3 rounded-xl border border-slate-100 p-3 dark:border-white/5"
                  >
                    <div className={`mt-0.5 rounded-full p-2 ${m.tone}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-white">{m.label}</span>
                        {ev.lead_name && (
                          <Link
                            href={`/leads/${ev.lead_id}`}
                            className="text-sm font-medium text-violet-600 hover:underline dark:text-violet-300"
                          >
                            {ev.lead_name}
                          </Link>
                        )}
                        {ev.stage && <Badge variant="outline" className="text-[10px]">{ev.stage}</Badge>}
                        <span className="ml-auto text-[11px] text-slate-400">{formatTime(ev.ts)}</span>
                      </div>
                      {ev.reason && (
                        <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">{ev.reason}</p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
