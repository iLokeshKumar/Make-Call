"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/utils/apiFetch";
import {
  CheckCheck,
  ChevronDown,
  ChevronUp,
  Eye,
  Link2,
  Loader2,
  Mail,
  MailOpen,
  MousePointerClick,
  RefreshCw,
  Reply,
  Send,
  X } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

/**
 * How often the frontend re-fetches the email thread (ms).
 * The IMAP poller runs every 180 s on the backend, so 60 s here means new inbound replies appear within ≤1 min of being pulled from the inbox.
 * Set to 0 to disable auto-refresh entirely.
 */
const FRONTEND_REFRESH_MS = 60_000;


type EngagementEvent = {
  event_type: "open" | "click" | "reply" | string;
  created_at: string | null;
  payload: { target_url?: string };
};

type EmailMessage = {
  id: number;
  direction: "inbound" | "outbound" | string | null;
  content: string | null;                              // subject
  metadata_json: { body?: string; subject?: string; from?: string } | null;
  delivery_status: string | null;
  created_at: string | null;
  events: EngagementEvent[];
};

type Props = {
  leadId: number;
  leadEmail?: string | null;
  onSessionTimeout?: () => void;
};

function stripHtml(html: string) {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function fmt(ts: string | null) {
  if (!ts) return "";
  return new Date(ts).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit" });
}

function relTime(ts: string | null) {
  if (!ts) return "";
  const diff = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
  if (diff < 1) return "just now";
  if (diff < 60) return `${diff}m ago`;
  if (diff < 1440) return `${Math.round(diff / 60)}h ago`;
  return `${Math.round(diff / 1440)}d ago`;
}

function EventBadges({ events }: { events: EngagementEvent[] }) {
  if (!events.length) return null;

  const opens = events.filter((e) => e.event_type === "open");
  const clicks = events.filter((e) => e.event_type === "click");
  const replies = events.filter((e) => e.event_type === "reply");

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {opens.length > 0 && (
        <span
          title={`Opened ${opens.length}× — last: ${fmt(opens[opens.length - 1].created_at)}`}
          className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300 cursor-default"
        >
          <MailOpen className="h-3 w-3" />
          Opened {opens.length > 1 ? `×${opens.length}` : ""} · {relTime(opens[opens.length - 1].created_at)}
        </span>
      )}
      {clicks.length > 0 && (
        <span
          title={clicks.map((c) => c.payload.target_url || "link").join(", ")}
          className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/20 dark:text-blue-300 cursor-default"
        >
          <MousePointerClick className="h-3 w-3" />
          {clicks.length} click{clicks.length > 1 ? "s" : ""}
        </span>
      )}
      {replies.length > 0 && (
        <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-500/20 dark:text-violet-300 cursor-default">
          <Reply className="h-3 w-3" />
          Replied
        </span>
      )}
    </div>
  );
}


function DeliveryDot({ status }: { status: string | null }) {
  const map: Record<string, { color: string; label: string; Icon: React.ElementType }> = {
    sent:      { color: "text-slate-400",                  label: "Sent",      Icon: CheckCheck },
    delivered: { color: "text-emerald-500 dark:text-emerald-400", label: "Delivered", Icon: CheckCheck },
    failed:    { color: "text-red-500",                    label: "Failed",    Icon: CheckCheck },
    pending:   { color: "text-amber-500",                  label: "Pending",   Icon: CheckCheck },
    received:  { color: "text-blue-500",                   label: "Received",  Icon: Mail } };
  const s = map[status ?? ""] ?? map.sent;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${s.color}`} title={s.label}>
      <s.Icon className="h-3 w-3" />
      {s.label}
    </span>
  );
}

function EmailCard({
  msg, onRemove
}: {
  msg: EmailMessage;
  onRemove?: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [removing, setRemoving] = useState(false);
  const isInbound = msg.direction === "inbound";

  const subject =
    msg.metadata_json?.subject || msg.content || "(no subject)";
  const rawBody = msg.metadata_json?.body ?? "";
  const bodyText = rawBody ? stripHtml(rawBody) : "";
  const fromLabel = isInbound
    ? (msg.metadata_json?.from ?? "Lead")
    : "You";

  return (
    <div
      className={`relative group rounded-2xl border text-sm transition-all ${
        isInbound
          ? "border-slate-200 bg-white dark:border-white/10 dark:bg-slate-900/40"
          : "border-blue-200 bg-blue-50 dark:border-blue-500/20 dark:bg-blue-500/5"
      }`}
    >
      {/* header row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
      >
        {/* avatar */}
        <div
          className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${
            isInbound
              ? "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300"
              : "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300"
          }`}
        >
          {isInbound ? "L" : "U"}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400">{fromLabel}</span>
            <span className="font-semibold text-slate-800 dark:text-slate-100 truncate">
              {subject}
            </span>
          </div>
          {!expanded && bodyText && (
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 truncate">
              {bodyText}
            </p>
          )}
          {/* engagement badges only on outbound */}
          {!isInbound && !expanded && <EventBadges events={msg.events} />}
        </div>

        {/* right meta */}
        <div className="flex-shrink-0 flex flex-col items-end gap-1 ml-2">
          <div className="flex items-center gap-1.5">
            <DeliveryDot status={msg.delivery_status} />
            <span className="text-xs text-slate-400 dark:text-slate-500 whitespace-nowrap">
              {fmt(msg.created_at)}
            </span>
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-slate-400" />
            ) : (
              <ChevronDown className="h-4 w-4 text-slate-400" />
            )}
          </div>
        </div>
      </button>

      {/* remove button — shown on hover, outside the expand toggle */}
      {onRemove && (
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            title="Remove from thread"
            disabled={removing}
            onClick={async (e) => {
              e.stopPropagation();
              if (!window.confirm("Remove this email from the thread? It won't be deleted permanently.")) return;
              setRemoving(true);
              await onRemove(msg.id);
              setRemoving(false);
            }}
            className="flex items-center justify-center h-6 w-6 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-white/10 text-slate-400 hover:text-red-500 hover:border-red-300 dark:hover:border-red-500/40 shadow-sm transition-all disabled:opacity-40"
          >
            {removing ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
          </button>
        </div>
      )}

      {/* expanded body */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {bodyText ? (
            <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-900 px-4 py-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed max-h-72 overflow-y-auto whitespace-pre-wrap">
              {bodyText}
            </div>
          ) : (
            <p className="text-xs text-slate-400 italic">No body content.</p>
          )}

          {/* engagement events list */}
          {!isInbound && msg.events.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                Activity
              </p>
              <EventBadges events={msg.events} />
              <ul className="space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                {msg.events.map((ev, i) => (
                  <li key={i} className="flex items-center gap-2">
                    {ev.event_type === "open" && <Eye className="h-3 w-3 text-emerald-500" />}
                    {ev.event_type === "click" && <Link2 className="h-3 w-3 text-blue-500" />}
                    {ev.event_type === "reply" && <Reply className="h-3 w-3 text-violet-500" />}
                    <span className="capitalize">{ev.event_type}</span>
                    {ev.payload.target_url && (
                      <span className="truncate max-w-[200px] opacity-70">{ev.payload.target_url}</span>
                    )}
                    <span className="ml-auto">{fmt(ev.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function EmailThread({ leadId, leadEmail, onSessionTimeout }: Props) {
  const [emails, setEmails] = useState<EmailMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [showCompose, setShowCompose] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track whether the user is actively composing so we don't interrupt them
  const isComposingRef = useRef(false);

  const fetchThread = useCallback(async (silent = false) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/email`, {
      });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      if (!res.ok) throw new Error("Failed to load email thread");
      const data = await res.json();
      setEmails(data.items ?? []);
      setLastRefreshed(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load email thread");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [leadId, onSessionTimeout]);

  // Initial load
  useEffect(() => { fetchThread(false); }, [fetchThread]);

  // Smart auto-refresh:
  // - Only ticks when the browser tab is visible
  // - Skips the tick if the user is actively composing a reply
  // - Clears on unmount to avoid memory leaks
  useEffect(() => {
    if (!FRONTEND_REFRESH_MS) return;

    intervalRef.current = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (isComposingRef.current) return;
      fetchThread(true); // silent=true → no full loading spinner
    }, FRONTEND_REFRESH_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchThread]);

  // Scroll to bottom when new emails arrive
  useEffect(() => {
    if (!loading) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [emails, loading]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!subject.trim() || !body.trim() || sending) return;
    setSending(true); setError(null);
    isComposingRef.current = false; // done composing
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/email/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: subject.trim(), body: body.trim() }) });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Send failed");
      }
      setSubject(""); setBody(""); setShowCompose(false);
      await fetchThread(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send email");
    } finally { setSending(false); }
  }

  const handleRemove = useCallback(async (interactionId: number) => {
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/email/${interactionId}`, {
        method: "DELETE"
      });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      // Optimistically remove from local state immediately
      setEmails((prev) => prev.filter((e) => e.id !== interactionId));
    } catch {
      // ignore — thread will re-sync on next refresh
    }
  }, [leadId, onSessionTimeout]);

  const outbound = emails.filter((e) => e.direction !== "inbound");
  const inbound  = emails.filter((e) => e.direction === "inbound");

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 flex flex-col overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-500/10">
          <Mail className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-white">Email Thread</h3>
          {leadEmail && (
            <p className="text-xs text-slate-500 dark:text-slate-400">{leadEmail}</p>
          )}
        </div>
        <div className="ml-auto flex items-center gap-3">
          {/* stat pills */}
          <div className="hidden sm:flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1">
              <Send className="h-3 w-3" /> {outbound.length} sent
            </span>
            <span className="inline-flex items-center gap-1">
              <Reply className="h-3 w-3" /> {inbound.length} replies
            </span>
            {outbound.some((e) => e.events.some((ev) => ev.event_type === "open")) && (
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                <MailOpen className="h-3 w-3" /> opened
              </span>
            )}
          </div>
          {/* last refreshed + manual refresh */}
          {lastRefreshed && (
            <span className="hidden sm:block text-xs text-slate-400 dark:text-slate-500">
              {lastRefreshed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <button
            type="button"
            title="Refresh inbox"
            onClick={() => fetchThread(true)}
            disabled={refreshing}
            className="inline-flex items-center justify-center rounded-lg p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-500/10 transition disabled:opacity-40"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
          <button
            type="button"
            onClick={() => setShowCompose((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 transition"
          >
            <Send className="h-3.5 w-3.5" />
            Compose
          </button>
        </div>
      </div>

      {/* compose box */}
      {showCompose && (
        <form onSubmit={handleSend} className="border-b border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-900/60 px-5 py-4 space-y-3">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject *"
            required
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-white/10 dark:bg-slate-900/40"
          />
          <textarea
            value={body}
            onChange={(e) => { setBody(e.target.value); isComposingRef.current = true; }}
            onBlur={() => { if (!body.trim()) isComposingRef.current = false; }}
            placeholder="Write your message..."
            required
            rows={5}
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-white/10 dark:bg-slate-900/40 resize-none"
          />
          <div className="flex items-center gap-2 justify-end">
            <button
              type="button"
              onClick={() => { setShowCompose(false); setSubject(""); setBody(""); isComposingRef.current = false; }}
              className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={sending || !subject.trim() || !body.trim()}
              className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Send
            </button>
          </div>
        </form>
      )}

      {/* thread */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 max-h-[32rem]">
        {loading ? (
          <div className="flex justify-center py-8 text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : emails.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-slate-400 dark:text-slate-500">
            <Mail className="h-8 w-8 mb-2 opacity-30" />
            <p className="text-sm">No emails yet.</p>
            <button
              type="button"
              onClick={() => setShowCompose(true)}
              className="mt-3 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Send the first email →
            </button>
          </div>
        ) : (
          emails.map((msg) => <EmailCard key={msg.id} msg={msg} onRemove={handleRemove} />)
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <p className="px-5 py-2 text-xs text-red-500 dark:text-red-400 border-t border-slate-200 dark:border-white/10">
          {error}
        </p>
      )}
    </div>
  );
}
