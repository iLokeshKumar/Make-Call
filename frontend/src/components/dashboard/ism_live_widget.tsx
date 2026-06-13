"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Activity, Mail, MessageCircle, Phone, UserCheck, Trophy, XCircle, AlertTriangle } from "lucide-react";

import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");
const WS_BASE = API_BASE.replace(/^http/, "ws");
const MAX_EVENTS = 8;

type IsmEvent = {
  type: "ism_activity" | "ping";
  lead_id?: number | null;
  lead_name?: string | null;
  stage?: string | null;
  action?: string;
  reason?: string | null;
  ts?: string;
};

const ICON_BY_ACTION: Record<string, React.ComponentType<{ className?: string }>> = {
  dispatched_email:    Mail,
  dispatched_whatsapp: MessageCircle,
  dispatched_call:     Phone,
  handoff:             UserCheck,
  auto_closed_won:     Trophy,
  auto_closed_lost:    XCircle,
  dispatch_failed:     AlertTriangle,
};

const LABEL_BY_ACTION: Record<string, string> = {
  dispatched_email:    "Email sent",
  dispatched_whatsapp: "WhatsApp sent",
  dispatched_call:     "Call queued",
  handoff:             "Handoff",
  auto_closed_won:     "Auto-Won",
  auto_closed_lost:    "Auto-Lost",
  dispatch_failed:     "Dispatch error",
};

function formatTime(iso?: string) {
  if (!iso) return "";
  try {
    const dt = new Date(iso);
    const diffMs = Date.now() - dt.getTime();
    if (diffMs < 60_000) return "just now";
    if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
    return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function IsmLiveWidget() {
  const { user } = useAuth();
  const [events, setEvents] = useState<IsmEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!user?.company_id) return;
    const ws = new WebSocket(`${WS_BASE}/ws/ism-activity/${user.company_id}`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as IsmEvent;
        if (msg.type !== "ism_activity") return;
        setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
      } catch {
        // ignore
      }
    };
    return () => { ws.close(); };
  }, [user?.company_id]);

  return (
    <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-violet-500" />
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Live Agent Activity</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-slate-400"}`} />
          <Link href="/agents/activity" className="text-xs font-semibold text-violet-600 hover:underline dark:text-violet-300">
            Full feed →
          </Link>
        </div>
      </div>

      {events.length === 0 ? (
        <p className="text-xs text-slate-500 dark:text-slate-400 italic">
          {connected ? "Listening… events appear as the ISM agent acts." : "Connecting…"}
        </p>
      ) : (
        <ul className="space-y-2">
          {events.map((ev, idx) => {
            const Icon = ICON_BY_ACTION[ev.action || ""] || Activity;
            const label = LABEL_BY_ACTION[ev.action || ""] || ev.action;
            return (
              <li key={`${ev.ts}-${idx}`} className="flex items-start gap-2 text-xs">
                <Icon className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-violet-500" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-slate-900 dark:text-white">{label}</span>
                    {ev.lead_name && (
                      <Link href={`/leads/${ev.lead_id}`} className="truncate text-violet-600 hover:underline dark:text-violet-300">
                        {ev.lead_name}
                      </Link>
                    )}
                    <span className="ml-auto flex-shrink-0 text-[10px] text-slate-400">{formatTime(ev.ts)}</span>
                  </div>
                  {ev.reason && (
                    <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{ev.reason}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
