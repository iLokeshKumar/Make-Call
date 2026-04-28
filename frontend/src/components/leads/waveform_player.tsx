"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Pause, Play, Volume2 } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
type TranscriptLine = {
  speaker: "AI" | "User" | string;
  text: string;
  /** Approximate start time in seconds from call start. Estimated from line index. */
  approxStart?: number;
};

type Props = {
  /** Legacy: directly-usable (public / blob) URL. */
  recordingUrl?: string;
  /**
   * When set, the player fetches the recording through the backend proxy with Bearer auth, builds a blob URL, and uses that everywhere. Needed because raw Twilio recording URLs require HTTP Basic auth that an <audio> tag cannot send.
   */
  interactionId?: number;
  token?: string;
  apiBase?: string;
  transcript?: string | null;
  duration?: number | null;
};

const DEFAULT_API_BASE =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL) || "http://localhost:6060";

function parseTranscriptLines(raw: string | null | undefined): TranscriptLine[] {
  if (!raw) return [];
  return raw
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/^(AI|User|Rio|Agent|Lead|Customer):\s*(.*)/i);
      if (m) return { speaker: m[1], text: m[2] };
      return { speaker: "unknown", text: line };
    });
}

export default function WaveformPlayer({ recordingUrl, interactionId, apiBase, transcript, duration }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);

  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [totalDuration, setTotalDuration] = useState(duration ?? 0);
  const [volume, setVolume] = useState(1);
  const [loading, setLoading] = useState(true);
  const [waveformData, setWaveformData] = useState<number[]>([]);
  const [activeLineIndex, setActiveLineIndex] = useState<number>(-1);
  const [effectiveUrl, setEffectiveUrl] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const lines = parseTranscriptLines(transcript);
  const lineCount = lines.length;

  // Annotate lines with approximate timestamps (uniformly distributed over call duration)
  const annotatedLines = lines.map((l, i) => ({
    ...l,
    approxStart: lineCount > 1 ? (i / (lineCount - 1)) * totalDuration : 0 }));

  // Resolve the playable URL: either a direct prop, or a blob URL produced by fetching the backend proxy with Bearer auth.
  useEffect(() => {
    let cancelled = false;
    let revoke: string | null = null;

    async function resolveUrl() {
      if (recordingUrl) {
        setEffectiveUrl(recordingUrl);
        return;
      }
      if (!interactionId ) return;
      try {
        setFetchError(null);
        const base = apiBase ?? DEFAULT_API_BASE;
        const res = await apiFetch(`${base}/crm/interactions/${interactionId}/recording`, {
        });
        if (!res.ok) {
          setFetchError(res.status === 404 ? "Recording not yet available" : `Failed to load (${res.status})`);
          return;
        }
        const blob = await res.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        revoke = url;
        setEffectiveUrl(url);
      } catch (e) {
        if (!cancelled) setFetchError(e instanceof Error ? e.message : "Failed to fetch recording");
      }
    }

    resolveUrl();
    return () => {
      cancelled = true;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [recordingUrl, interactionId, apiBase]);

  // Decode audio + build waveform via Web Audio API
  const buildWaveform = useCallback(async () => {
    if (!effectiveUrl) return;
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const resp = await apiFetch(effectiveUrl);
      if (!resp.ok) return;
      const arrayBuf = await resp.arrayBuffer();
      const audioBuf = await ctx.decodeAudioData(arrayBuf);
      const raw = audioBuf.getChannelData(0);
      const buckets = 120;
      const step = Math.floor(raw.length / buckets);
      const data: number[] = [];
      for (let i = 0; i < buckets; i++) {
        let sum = 0;
        for (let j = 0; j < step; j++) {
          sum += Math.abs(raw[i * step + j] || 0);
        }
        data.push(sum / step);
      }
      // Normalise to 0-1
      const max = Math.max(...data, 0.001);
      setWaveformData(data.map((v) => v / max));
      await ctx.close();
    } catch {

    }
  }, [effectiveUrl]);

  useEffect(() => { buildWaveform(); }, [buildWaveform]);

  // Draw waveform on canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || waveformData.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      const barW = width / waveformData.length;
      const progress = totalDuration > 0 ? currentTime / totalDuration : 0;

      waveformData.forEach((v, i) => {
        const barHeight = Math.max(3, v * height * 0.85);
        const x = i * barW;
        const y = (height - barHeight) / 2;
        const isPast = i / waveformData.length <= progress;
        ctx.fillStyle = isPast ? "#7c3aed" : "#e2e8f0";
        ctx.beginPath();
        ctx.roundRect(x + 1, y, barW - 2, barHeight, 2);
        ctx.fill();
      });

      animFrameRef.current = requestAnimationFrame(draw);
    };

    animFrameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [waveformData, currentTime, totalDuration]);

  function handleLoadedMetadata() {
    if (audioRef.current) {
      setTotalDuration(audioRef.current.duration);
      setLoading(false);
    }
  }

  function handleTimeUpdate() {
    const t = audioRef.current?.currentTime ?? 0;
    setCurrentTime(t);

    // Highlight active transcript line
    let idx = -1;
    for (let i = annotatedLines.length - 1; i >= 0; i--) {
      if (t >= (annotatedLines[i].approxStart ?? 0)) {
        idx = i;
        break;
      }
    }
    setActiveLineIndex(idx);
  }

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.play();
      setPlaying(true);
    }
  }

  function handleSeek(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    const audio = audioRef.current;
    if (!canvas || !audio || totalDuration === 0) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    audio.currentTime = ratio * totalDuration;
  }

  function formatTime(s: number) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-500/10">
          <Volume2 className="h-4 w-4 text-violet-600 dark:text-violet-400" />
        </div>
        <h3 className="font-semibold text-slate-900 dark:text-white">Call Recording</h3>
        {totalDuration > 0 && (
          <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
            {formatTime(totalDuration)}
          </span>
        )}
      </div>

      {/* Side-by-side on lg+: audio controls left, transcript right.
          Stacks vertically on smaller screens. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-5">
        {/* LEFT: audio + waveform + controls */}
        <div className="space-y-4 min-w-0">
          {effectiveUrl && (
            <audio
              ref={audioRef}
              src={effectiveUrl}
              onLoadedMetadata={handleLoadedMetadata}
              onTimeUpdate={handleTimeUpdate}
              onEnded={() => setPlaying(false)}
              preload="metadata"
            />
          )}

          {fetchError && (
            <p className="text-xs text-amber-500 font-medium">{fetchError}</p>
          )}

          {/* Waveform canvas */}
          <div className="relative">
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center text-slate-400">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            )}
            <canvas
              ref={canvasRef}
              width={600}
              height={64}
              onClick={handleSeek}
              className="w-full h-16 cursor-pointer rounded-xl bg-slate-50 dark:bg-slate-900/40"
            />
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3">
            <button
              onClick={togglePlay}
              disabled={loading}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition"
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
            </button>

            <span className="text-xs font-mono text-slate-500 dark:text-slate-400 w-20">
              {formatTime(currentTime)} / {formatTime(totalDuration)}
            </span>

            <div className="flex items-center gap-1.5 ml-auto">
              <Volume2 className="h-3.5 w-3.5 text-slate-400" />
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={volume}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setVolume(v);
                  if (audioRef.current) audioRef.current.volume = v;
                }}
                className="w-20 accent-violet-500"
              />
            </div>
          </div>
        </div>

        {/* RIGHT: transcript sync panel */}
        {annotatedLines.length > 0 ? (
          <div className="max-h-[400px] lg:max-h-[300px] overflow-y-auto space-y-1 rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-900/30 p-3 min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400 mb-2 sticky top-0 bg-slate-50 dark:bg-slate-900/30 py-1 -mx-3 px-3">
              Transcript ({annotatedLines.length} lines)
            </p>
            {annotatedLines.map((line, i) => {
              const isAI = /ai|rio|agent/i.test(line.speaker);
              const isActive = i === activeLineIndex;
              return (
                <div
                  key={i}
                  className={`flex gap-2 rounded-lg px-2 py-1 text-xs transition-colors ${
                    isActive
                      ? "bg-violet-100 dark:bg-violet-500/20"
                      : "hover:bg-slate-100 dark:hover:bg-white/5"
                  }`}
                >
                  <span
                    className={`flex-shrink-0 font-semibold ${
                      isAI
                        ? "text-violet-600 dark:text-violet-400"
                        : "text-emerald-600 dark:text-emerald-400"
                    }`}
                  >
                    {line.speaker}:
                  </span>
                  <span className="text-slate-700 dark:text-slate-300 leading-relaxed break-words">
                    {line.text}
                  </span>
                  <span className="ml-auto flex-shrink-0 text-slate-400 dark:text-slate-500 font-mono">
                    {formatTime(line.approxStart ?? 0)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex items-center justify-center rounded-xl border border-dashed border-slate-200 dark:border-white/10 p-6">
            <p className="text-xs text-slate-500 italic">No transcript available</p>
          </div>
        )}
      </div>
    </div>
  );
}
