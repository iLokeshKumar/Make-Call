"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, Send } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type WaMessage = {
  id: number;
  direction: "inbound" | "outbound" | string | null;
  content: string | null;
  delivery_status: string | null;
  created_at: string | null;
};

type Props = {
  leadId: number;
  onSessionTimeout?: () => void;
};

export default function WhatsAppThread({ leadId, onSessionTimeout }: Props) {
  const [messages, setMessages] = useState<WaMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sendText, setSendText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const fetchThread = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/whatsapp`, {
      });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      if (!res.ok) throw new Error("Failed to load thread");
      const data = await res.json();
      setMessages(data.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load WhatsApp thread");
    } finally {
      setLoading(false);
    }
  }, [leadId, onSessionTimeout]);

  useEffect(() => { fetchThread(); }, [fetchThread]);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!sendText.trim() || sending) return;
    setSending(true);
    setError(null);
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/whatsapp/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: sendText.trim() }) });
      if (res.status === 401) { onSessionTimeout?.(); return; }
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.detail || "Send failed");
      }
      setSendText("");
      await fetchThread();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Message send failed");
    } finally {
      setSending(false);
    }
  }

  function formatTime(ts: string | null) {
    if (!ts) return "";
    return new Date(ts).toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit" });
  }

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-500/10">
          <MessageSquare className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h3 className="font-semibold text-slate-900 dark:text-white">WhatsApp Conversation</h3>
        <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
          {messages.length} message{messages.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 max-h-80">
        {loading ? (
          <div className="flex justify-center py-8 text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-slate-400 dark:text-slate-500">
            <MessageSquare className="h-8 w-8 mb-2 opacity-30" />
            <p className="text-sm">No WhatsApp messages yet.</p>
          </div>
        ) : (
          messages.map((msg) => {
            const isOut = msg.direction === "outbound";
            return (
              <div
                key={msg.id}
                className={`flex ${isOut ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                    isOut
                      ? "rounded-br-sm bg-emerald-500 text-white"
                      : "rounded-bl-sm bg-white text-slate-800 border border-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:border-white/10"
                  }`}
                >
                  <p className="leading-relaxed">{msg.content || "(empty)"}</p>
                  <div className={`mt-1 flex items-center gap-1 text-xs ${isOut ? "text-emerald-100 justify-end" : "text-slate-400 dark:text-slate-500"}`}>
                    <span>{formatTime(msg.created_at)}</span>
                    {isOut && msg.delivery_status && (
                      <span>· {msg.delivery_status}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      {/* Send box */}
      {error && (
        <p className="px-4 py-1 text-xs text-red-500 dark:text-red-400">{error}</p>
      )}
      <form
        onSubmit={handleSend}
        className="flex items-center gap-2 border-t border-slate-200 px-4 py-3 dark:border-white/10"
      >
        <input
          value={sendText}
          onChange={(e) => setSendText(e.target.value)}
          placeholder="Type a message..."
          className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-emerald-400 dark:border-white/10 dark:bg-slate-900/40"
          disabled={sending}
        />
        <button
          type="submit"
          disabled={sending || !sendText.trim()}
          className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500 text-white shadow transition hover:bg-emerald-600 disabled:opacity-50"
        >
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </div>
  );
}
