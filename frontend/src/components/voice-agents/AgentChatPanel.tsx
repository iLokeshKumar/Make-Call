"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, PhoneCall, Send, Square, Wrench } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";
import { useVoiceSearch } from "@/hooks/useVoiceSearch";

type Message = { role: "user" | "assistant" | "tool"; content: string };

export default function AgentChatPanel({ agentId, initialMode = "chat" }: { agentId: number; initialMode?: "chat" | "web_call" }) {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<{ context: AudioContext; source: MediaStreamAudioSourceNode; processor: ScriptProcessorNode; stream: MediaStream } | null>(null);
  const playbackRef = useRef<AudioContext | null>(null);

  const { listening, supported, toggle } = useVoiceSearch((text) => {
    setInput((current) => current.trim() ? `${current.trim()} ${text}` : text);
  });

  useEffect(() => () => stopWebCall(), []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, activity]);

  async function createSession(transport: "chat" | "web_call") {
    const response = await apiFetch(`${API_BASE}/crm/agent-chat/sessions`, { method: "POST", body: JSON.stringify({ agent_id: agentId, transport }) });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not create session");
    const data = await response.json(); setSessionId(data.session_id); return data;
  }

  async function sendMessage() {
    const text = input.trim(); if (!text || busy) return;
    setInput(""); setBusy(true); setMessages((old) => [...old, { role: "user", content: text }]);
    try {
      const id = sessionId || (await createSession("chat")).session_id;
      const response = await apiFetch(`${API_BASE}/crm/agent-chat/sessions/${id}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      if (!response.ok || !response.body) throw new Error("Chat request failed");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let reply = "";
      setActivity("Thinking…");
      for (;;) {
        const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n"); buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((item) => item.startsWith("data: ")); if (!line) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === "token" || event.type === "message") {
            reply = event.type === "token" ? reply + (event.content || "") : event.content || "";
            setActivity(null);
            setMessages((old) => old[old.length - 1]?.role === "assistant" ? [...old.slice(0, -1), { role: "assistant", content: reply }] : [...old, { role: "assistant", content: reply }]);
          }
          if (event.type === "tool_start") setActivity(`Using ${event.tool}…`);
          if (event.type === "tool_result") setActivity("Preparing your answer…");
          if (event.type === "error") throw new Error(event.message || "The agent could not complete that request");
        }
      }
    } catch (error) { setMessages((old) => [...old, { role: "assistant", content: error instanceof Error ? error.message : "Something went wrong" }]); }
    finally { setActivity(null); setBusy(false); }
  }

  async function startWebCall() {
    try {
      const data = await createSession("web_call");
      const socket = new WebSocket(`${API_BASE.replace(/^http/, "ws")}/ws/web-call?token=${encodeURIComponent(data.token)}`); wsRef.current = socket;
      socket.onerror = () => setActivity("Could not connect to the web call");
      socket.onopen = async () => {
        setConnected(true); setActivity("Connecting microphone…"); socket.send(JSON.stringify({ type: "start" }));
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); const context = new AudioContext({ sampleRate: 16000 });
        const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (event) => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const samples = event.inputBuffer.getChannelData(0); const pcm = new Int16Array(samples.length);
          for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 32767;
          const bytes = new Uint8Array(pcm.buffer); let binary = ""; for (const byte of bytes) binary += String.fromCharCode(byte);
          socket.send(JSON.stringify({ type: "audio", audio: btoa(binary) }));
        };
        source.connect(processor); processor.connect(context.destination); audioRef.current = { context, source, processor, stream }; setActivity(null);
      };
      socket.onmessage = (event) => {
        const data = JSON.parse(event.data); if (data.type !== "audio") return;
        const raw = Uint8Array.from(atob(data.audio), (char) => char.charCodeAt(0)); const context = playbackRef.current || new AudioContext({ sampleRate: 16000 }); playbackRef.current = context;
        const pcm = new Int16Array(raw.buffer, raw.byteOffset, Math.floor(raw.byteLength / 2)); const buffer = context.createBuffer(1, pcm.length, 16000); const channel = buffer.getChannelData(0);
        for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
        const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination); source.start();
      };
      socket.onclose = () => stopWebCall();
    } catch (error) { setActivity(error instanceof Error ? error.message : "Could not start web call"); setConnected(false); }
  }

  function stopWebCall() {
    audioRef.current?.stream.getTracks().forEach((track) => track.stop()); audioRef.current?.processor.disconnect(); audioRef.current?.source.disconnect(); void audioRef.current?.context.close(); audioRef.current = null;
    wsRef.current?.close(); wsRef.current = null; void playbackRef.current?.close(); playbackRef.current = null; setConnected(false);
  }

  return <section className="max-w-4xl space-y-5">
    {initialMode === "chat" ? <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white/60 shadow-sm dark:border-slate-800/40 dark:bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-200/60 px-5 py-4 dark:border-slate-800/60"><div><p className="text-sm font-semibold">Chat with your agent</p><p className="mt-0.5 text-xs text-slate-500">Test prompts, knowledge, and tools in real time</p></div><span className="inline-flex items-center gap-1.5 text-xs text-emerald-600"><span className="h-2 w-2 rounded-full bg-emerald-500" />Ready</span></div>
      <div ref={scrollRef} className="h-[28rem] space-y-3 overflow-y-auto p-5">{messages.length === 0 && <div className="flex h-full flex-col items-center justify-center text-center"><div className="mb-3 rounded-2xl bg-violet-100 p-3 text-violet-600 dark:bg-violet-950/40"><PhoneCall className="h-5 w-5" /></div><p className="text-sm font-medium">Start a conversation</p><p className="mt-1 max-w-xs text-xs text-slate-500">Ask about your product, policies, or anything covered by this agent.</p></div>}{messages.map((message, index) => <div key={index} className={`max-w-[82%] rounded-xl px-4 py-3 text-sm leading-6 ${message.role === "user" ? "ml-auto bg-violet-600 text-white" : message.role === "tool" ? "bg-amber-50 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200" : "bg-slate-100 dark:bg-slate-800"}`}>{message.role === "tool" && <Wrench className="mr-2 inline h-3.5 w-3.5" />}{message.content}</div>)}{activity && <div className="flex items-center gap-2 text-xs text-slate-500"><span className="flex gap-1"><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-500" /><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-500 [animation-delay:120ms]" /><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-500 [animation-delay:240ms]" /></span>{activity}</div>}</div>
      <div className="border-t border-slate-200/60 p-4 dark:border-slate-800/60"><div className="flex gap-2"><div className="relative flex-1"><input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void sendMessage()} placeholder={listening ? "Listening…" : "Ask this agent anything…"} disabled={busy} className={`w-full rounded-xl border bg-transparent px-4 py-3 pr-12 text-sm outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 disabled:opacity-60 dark:border-slate-700 ${listening ? "border-violet-500 ring-2 ring-violet-500/20" : "border-slate-200"}`} />{supported && <button type="button" onClick={toggle} disabled={busy} aria-label={listening ? "Stop voice input" : "Start voice input"} title={listening ? "Stop listening" : "Voice input"} className={`absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2 transition ${listening ? "bg-violet-100 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300" : "text-slate-400 hover:bg-slate-100 hover:text-violet-500 dark:hover:bg-slate-800"}`}>{listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}</button>}</div><button onClick={() => void sendMessage()} disabled={busy || !input.trim()} className="rounded-xl bg-violet-600 px-4 text-white transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"><Send className="h-4 w-4" /></button></div><p className="mt-2 px-1 text-[11px] text-slate-400">Enter to send · {supported ? "Use the microphone for voice input · " : ""}Responses use this agent’s configured tools</p></div>
    </div> : <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-10 text-center shadow-sm dark:border-slate-800/40 dark:bg-slate-900/40"><div className={`mx-auto flex h-24 w-24 items-center justify-center rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-violet-100 dark:bg-violet-950/40"}`}>{connected ? <Mic className="h-9 w-9 text-white" /> : <PhoneCall className="h-9 w-9 text-violet-600" />}</div><div className="mt-5 inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 dark:bg-slate-800">{connected ? "Live · microphone connected" : "Browser voice · no phone number required"}</div><h3 className="mt-4 text-xl font-bold">{connected ? "Agent is listening" : "Talk to this agent in your browser"}</h3><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">Web Call uses the selected agent’s prompt, tools, knowledge, and voice runtime without dialing a phone.</p>{activity && <p className="mt-4 text-xs text-violet-600">{activity}</p>}<button onClick={() => connected ? stopWebCall() : void startWebCall()} className={`mt-6 inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-white transition ${connected ? "bg-red-600 hover:bg-red-700" : "bg-violet-600 hover:bg-violet-700"}`}>{connected ? <><Square className="h-4 w-4" />End Web Call</> : <><Mic className="h-4 w-4" />Start Web Call</>}</button></div>}
  </section>;
}
