"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { Phone, PhoneCall, PhoneOff, Loader2, UserCheck, Database, Sparkles, X, ExternalLink } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";
const WS_BASE = API_BASE.replace(/^http/, "ws");

// Types

type CallStatus = "ringing" | "connected" | "ended";

interface CallRow {
  call_task_id: number | null;
  interaction_id: string | null;
  campaign_id: number | null;
  lead_id: number | null;
  lead_name: string | null;
  status: CallStatus;
  outcome: string | null;
  ts: string;                     // ISO timestamp of latest status event
  connected_at: string | null;    // ISO timestamp when status became "connected"
}

interface Campaign {
  id: number;
  name: string;
}

// Helpers

function humanize(v?: string | null) {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function rowKey(msg: { call_task_id: number | null; interaction_id: string | null }) {
  return msg.call_task_id != null
    ? `task-${msg.call_task_id}`
    : `iid-${msg.interaction_id ?? "unknown"}`;
}

function StatusBadge({ status, outcome }: { status: CallStatus; outcome: string | null }) {
  if (status === "ringing") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300">
        <Phone className="w-3 h-3 animate-pulse" /> Ringing
      </span>
    );
  }
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">
        <PhoneCall className="w-3 h-3" /> Connected
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
      <PhoneOff className="w-3 h-3" /> {humanize(outcome) || "Ended"}
    </span>
  );
}

function LiveTimer({ connectedAt }: { connectedAt: string | null }) {
  const [secs, setSecs] = useState(0);

  useEffect(() => {
    if (!connectedAt) { setSecs(0); return; }
    const tick = () =>
      setSecs(Math.floor((Date.now() - new Date(connectedAt).getTime()) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [connectedAt]);

  if (!connectedAt) return <span className="text-gray-400">—</span>;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return (
    <span className="font-mono text-sm">
      {m}:{String(s).padStart(2, "0")}
    </span>
  );
}

// Warm Transfer Modal

function WarmTransferModal({
  row, onClose }: {
  row: CallRow;
  onClose: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function handleTransfer() {
    const interactionId = Number(row.interaction_id);
    if (!phone.trim() || !interactionId) return;
    setTransferring(true);
    setError("");
    try {
      const params = new URLSearchParams({
        interaction_id: String(interactionId),
        transfer_to: phone.trim() });
      if (name.trim()) params.set("isr_name", name.trim());
      const res = await apiFetch(`${API_BASE}/telephony/warm-transfer?${params}`, {
        method: "POST"
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Transfer failed");
      }
      setSuccess(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transfer failed");
    } finally {
      setTransferring(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-2xl space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 font-bold text-gray-900 dark:text-white text-sm">
            <UserCheck className="h-4 w-4 text-violet-500" />
            Warm Transfer to ISR
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 dark:hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>

        {success ? (
          <div className="rounded-xl bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 p-4 text-sm text-green-700 dark:text-green-300 text-center">
            <PhoneCall className="h-5 w-5 mx-auto mb-2" />
            Transfer initiated — bridging to ISR.
          </div>
        ) : (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Call with <span className="font-semibold text-gray-700 dark:text-gray-200">{row.lead_name ?? `Lead #${row.lead_id}`}</span> will be
              bridged to the ISR in real-time. The AI stays on hold until the ISR connects.
            </p>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  ISR Phone Number <span className="text-red-400">*</span>
                </label>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+91 98765 43210"
                  className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                  ISR Name <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Ravi Kumar"
                  className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>
            </div>
            {error && <p className="text-xs text-red-500">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-xl border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm font-semibold text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleTransfer}
                disabled={transferring || !phone.trim()}
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {transferring ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserCheck className="h-4 w-4" />}
                {transferring ? "Bridging…" : "Transfer"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Component

export default function CallMonitorPage() {
  const { user, sessionTimeout } = useAuth();

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<number | null>(null);
  const [rows, setRows] = useState<Map<string, CallRow>>(new Map());
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [transferRow, setTransferRow] = useState<CallRow | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!user) return;
    apiFetch(`${API_BASE}/crm/campaigns`, {
    })
      .then((r) => {
        if (r.status === 401) { sessionTimeout(); return null; }
        return r.ok ? r.json() : null;
      })
      .then((data) => {
        if (data?.campaigns) setCampaigns(data.campaigns);
        else if (Array.isArray(data)) setCampaigns(data);
      })
      .catch(() => {});
  }, [user, sessionTimeout]);

  // WebSocket
  useEffect(() => {
    if (!user || !user?.company_id) return;


    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const params = selectedCampaign != null ? `?campaign_id=${selectedCampaign}` : "";
    const url = `${WS_BASE}/ws/call-monitor/${user.company_id}${params}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => { setConnected(true); setError(null); };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setError("WebSocket connection failed — retrying on next page load.");

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string);
        if (msg.type === "ping") return;
        if (msg.type !== "call_status") return;

        const key = rowKey(msg);
        setRows((prev) => {
          const next = new Map(prev);
          const existing = next.get(key);
          next.set(key, {
            call_task_id: msg.call_task_id,
            interaction_id: msg.interaction_id,
            campaign_id: msg.campaign_id,
            lead_id: msg.lead_id,
            lead_name: msg.lead_name,
            status: msg.status,
            outcome: msg.outcome ?? existing?.outcome ?? null,
            ts: msg.ts,
            connected_at:
              msg.status === "connected"
                ? msg.ts
                : (existing?.connected_at ?? null) });
          return next;
        });
      } catch {
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [user, user?.company_id, selectedCampaign, sessionTimeout]);

  // Sorted: active calls first (ringing/connected), then ended by most recent
  const sorted = [...rows.values()].sort((a, b) => {
    const rank = (s: CallStatus) => (s === "connected" ? 0 : s === "ringing" ? 1 : 2);
    if (rank(a.status) !== rank(b.status)) return rank(a.status) - rank(b.status);
    return new Date(b.ts).getTime() - new Date(a.ts).getTime();
  });

  const activeCalls = sorted.filter((r) => r.status !== "ended").length;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Live Call Monitor
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Real-time status for all outbound calls
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Quick links */}
          <Link
            href="/knowledge"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-semibold text-gray-600 dark:text-gray-300 hover:border-violet-400 hover:text-violet-700 dark:hover:text-violet-300 transition"
          >
            <Database className="h-3.5 w-3.5" /> Knowledge Base
          </Link>
          <Link
            href="/knowledge#ask"
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-700 transition"
          >
            <Sparkles className="h-3.5 w-3.5" /> Ask Rio
          </Link>

          {/* Connection indicator */}
          <span
            className={`flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ${
              connected
                ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-green-500 animate-pulse" : "bg-gray-400"
              }`}
            />
            {connected ? "Live" : "Disconnected"}
          </span>

          {/* Active call count */}
          {activeCalls > 0 && (
            <span className="flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
              <Loader2 className="w-3 h-3 animate-spin" />
              {activeCalls} active
            </span>
          )}
        </div>
      </div>

      {/* Campaign filter */}
      <div className="mb-4 flex items-center gap-2">
        <label className="text-sm text-gray-600 dark:text-gray-400">Campaign:</label>
        <select
          value={selectedCampaign ?? ""}
          onChange={(e) =>
            setSelectedCampaign(e.target.value === "" ? null : Number(e.target.value))
          }
          className="text-sm border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        >
          <option value="">All campaigns</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        {rows.size > 0 && (
          <button
            onClick={() => setRows(new Map())}
            className="ml-auto text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            Clear history
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Table */}
      {rows.size === 0 ? (
        <div className="text-center py-20 text-gray-400 dark:text-gray-600">
          <Phone className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Waiting for calls…</p>
          <p className="text-xs mt-1">Events will appear here as calls are dialed.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/60 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Lead</th>
                <th className="px-4 py-3 text-left">Campaign</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Duration</th>
                <th className="px-4 py-3 text-left">Task ID</th>
                <th className="px-4 py-3 text-left">Last update</th>
                <th className="px-4 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700/50">
              {sorted.map((row) => {
                const key = rowKey(row);
                const isActive = row.status !== "ended";
                return (
                  <tr
                    key={key}
                    className={`transition-colors ${
                      isActive
                        ? "bg-white dark:bg-gray-900"
                        : "bg-gray-50/50 dark:bg-gray-800/30 opacity-70"
                    }`}
                  >
                    <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">
                      {row.lead_name ?? `Lead #${row.lead_id ?? "?"}`}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {row.campaign_id != null
                        ? (campaigns.find((c) => c.id === row.campaign_id)?.name ??
                           `#${row.campaign_id}`)
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.status} outcome={row.outcome} />
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                      {row.status === "connected" ? (
                        <LiveTimer connectedAt={row.connected_at} />
                      ) : row.status === "ended" && row.connected_at ? (
                        <span className="font-mono text-sm text-gray-400">
                          {Math.floor(
                            (new Date(row.ts).getTime() -
                              new Date(row.connected_at).getTime()) /
                              1000
                          )}s
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                      {row.call_task_id ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(row.ts).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        {/* Lead profile link */}
                        {row.lead_id && (
                          <Link
                            href={`/leads/${row.lead_id}`}
                            title="View lead profile"
                            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-violet-600 dark:hover:text-violet-400 transition"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Link>
                        )}
                        {/* KB context link */}
                        {isActive && (
                          <Link
                            href="/knowledge"
                            title="Search knowledge base"
                            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-blue-600 dark:hover:text-blue-400 transition"
                          >
                            <Database className="h-3.5 w-3.5" />
                          </Link>
                        )}
                        {/* Warm transfer */}
                        {row.status === "connected" && row.interaction_id && (
                          <button
                            title="Warm transfer to ISR"
                            onClick={() => setTransferRow(row)}
                            className="inline-flex items-center gap-1 rounded-lg bg-violet-100 dark:bg-violet-500/10 px-2 py-1 text-[11px] font-semibold text-violet-700 dark:text-violet-300 hover:bg-violet-200 dark:hover:bg-violet-500/20 transition"
                          >
                            <UserCheck className="h-3 w-3" /> Transfer
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {transferRow && user && (
        <WarmTransferModal
          row={transferRow}
          onClose={() => setTransferRow(null)}
        />
      )}
    </div>
  );
}
