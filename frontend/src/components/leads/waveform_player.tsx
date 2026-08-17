"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Pause, Play, Volume2 } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";
type Word = { text: string; start: number; end: number };

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
  const [playbackRate, setPlaybackRate] = useState(1);
  const [loading, setLoading] = useState(true);
  const [waveformData, setWaveformData] = useState<number[]>([]);
  const [activeLineIndex, setActiveLineIndex] = useState<number>(-1);
  const [activeWordIndex, setActiveWordIndex] = useState<number>(-1);
  const [effectiveUrl, setEffectiveUrl] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const lines = useMemo(() => parseTranscriptLines(transcript), [transcript]);
  const lineCount = lines.length;
  const [asrSegments, setAsrSegments] = useState<any[]>([]);

  // Fetch ASR segments from backend (table-backed). Falls back to metadata_json if not present.
  useEffect(() => {
    let cancelled = false;
    async function fetchSegments() {
      if (!interactionId) return;
      try {
        const base = apiBase ?? API_BASE;
        const res = await apiFetch(`${base}/crm/interactions/${interactionId}/asr_segments`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setAsrSegments(data || []);
      } catch (e) {
        // ignore
      }
    }
    fetchSegments();
    return () => { cancelled = true; };
  }, [interactionId, apiBase]);

  // Build per-line word timestamps and annotated lines using asrSegments when available
  const [annotatedLinesState, setAnnotatedLinesState] = useState(() => lines.map((l, i) => ({ ...l, approxStart: lineCount > 1 ? (i / (lineCount - 1)) * totalDuration : 0, words: [] as Word[] })));

  useEffect(() => {
    // Initialize with approximations
    let initial = lines.map((l, i) => ({ ...l, approxStart: lineCount > 1 ? (i / (lineCount - 1)) * totalDuration : 0, words: [] as Word[] }));
    if (asrSegments && asrSegments.length > 0) {
      // If counts match, map 1:1
      if (asrSegments.length === lines.length) {
        initial = lines.map((l, i) => ({
          ...l,
          approxStart: asrSegments[i]?.start ?? initial[i].approxStart,
          words: Array.isArray(asrSegments[i]?.word_json?.words) ? asrSegments[i].word_json.words : [],
        }));
      } else {
        // Try best-effort substring mapping and extract words if present
        initial = lines.map((l) => {
          // find the segment with best substring match
          let best = null;
          for (const seg of asrSegments) {
            try {
              if (!seg || !seg.text) continue;
              if ((l.text || "").toLowerCase().includes((seg.text || "").toLowerCase())) {
                best = seg;
                break;
              }
            } catch (e) {}
          }
          return {
            ...l,
            approxStart: best?.start ?? initial[0].approxStart,
            words: Array.isArray(best?.word_json?.words) ? best.word_json.words : [],
          };
        });
      }
    }
    setAnnotatedLinesState(initial);
  }, [asrSegments, lines, lineCount, totalDuration]);

  const annotatedLines = annotatedLinesState;

  // Resolve the playable URL: either a direct prop, or a blob URL produced by fetching the backend proxy with Bearer auth.
  useEffect(() => {
    let cancelled = false;
    let revoke: string | null = null;

    async function resolveUrl() {
      // Prefer backend proxy when interactionId is available to avoid exposing provider URLs
      if (interactionId) {
        try {
          setFetchError(null);
          const base = apiBase ?? API_BASE;
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
          return;
        } catch (e) {
          if (!cancelled) setFetchError(e instanceof Error ? e.message : "Failed to fetch recording");
          // fallback to direct URL below if available
        }
      }

      // Fallback: use provided public recording URL (may require CORS/auth)
      if (recordingUrl) {
        setEffectiveUrl(recordingUrl);
        return;
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
      const resp = await fetch(effectiveUrl as string);
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

      // Highlight active transcript line and word (if available)
    let idx = -1;
      let wordIdx = -1;
      for (let i = annotatedLines.length - 1; i >= 0; i--) {
        const start = annotatedLines[i].approxStart ?? 0;
        if (t >= start) {
          idx = i;

          // find active word within the line (word_json.words expected shape: [{text, start, end}])
          const words = annotatedLines[i].words || [];
          for (let w = 0; w < words.length; w++) {
            const word = words[w];
            const ws = (word.start ?? 0) + (start ?? 0);
            const we = (word.end ?? 0) + (start ?? 0);
            if (t >= ws && t <= we) {
              wordIdx = w;
              break;
            }
          }

          break;
        }
      }
      setActiveLineIndex(idx);
      setActiveWordIndex(wordIdx);

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

  // Reusable seek helper for transcript clicks
  function seekToTime(t: number, autoplay = true) {
    const audio = audioRef.current;
    if (!audio || typeof t !== "number") return;
    audio.currentTime = Math.max(0, Math.min(t, totalDuration || audio.duration || 0));
    if (autoplay) {
      audio.play().catch(() => {});
      setPlaying(true);
    }
  }

  function seekToWord(lineIndex: number, wordIndex: number) {
    const line = annotatedLines[lineIndex];
    if (!line || !line.words || !line.words[wordIndex]) return;
    const word = line.words[wordIndex];
    const lineStart = line.approxStart ?? 0;
    const target = (word.start ?? 0) + lineStart;
    seekToTime(target, true);
  }

  const transcriptContainerRef = useRef<HTMLDivElement | null>(null);
  const lineRefs = useRef<Array<HTMLDivElement | null>>([]);

  // Basic virtualization: render only visible slice based on scroll
  const [visibleStart, setVisibleStart] = useState(0);
  const [visibleEnd, setVisibleEnd] = useState(50);
  const LINE_HEIGHT = 34; // px per transcript line estimate

  useEffect(() => {
    if (!transcriptContainerRef.current) return;
    const el = transcriptContainerRef.current;
    function onScroll() {
      const scrollTop = el.scrollTop;
      const height = el.clientHeight;
      const start = Math.max(0, Math.floor(scrollTop / LINE_HEIGHT) - 5);
      const end = Math.min(annotatedLines.length, Math.ceil((scrollTop + height) / LINE_HEIGHT) + 5);
      setVisibleStart(start);
      setVisibleEnd(end);
    }
    el.addEventListener("scroll", onScroll);
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [annotatedLines.length]);

  useEffect(() => {
    if (activeLineIndex >= 0) {
      const el = lineRefs.current[activeLineIndex - visibleStart];
      if (el && transcriptContainerRef.current) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [activeLineIndex, visibleStart]);

  async function downloadRecording() {
    try {
      if (!interactionId) return;
      const base = apiBase ?? API_BASE;
      const res = await apiFetch(`${base}/crm/interactions/${interactionId}/recording`);
      if (!res.ok) return;
      const blob = await res.blob();
      const filename = `recording-${interactionId ?? "unknown"}.mp3`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Download failed", e);
    }
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
        <div className="ml-auto flex items-center gap-2">
          {totalDuration > 0 && (
            <span className="text-xs text-slate-500 dark:text-slate-400 mr-2">
              {formatTime(totalDuration)}
            </span>
          )}
          <button
            onClick={downloadRecording}
            aria-label="Download recording"
            className="text-xs px-2 py-1 rounded-md border border-slate-200 bg-white/50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-white/10"
          >
            Download
          </button>
        </div>
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
          <div className="space-y-2">
            {/* Row 1: play + time + volume */}
            <div className="flex items-center gap-3">
              <button
                onClick={togglePlay}
                disabled={loading}
                className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition"
              >
                {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
              </button>

              <span className="text-xs font-mono text-slate-500 dark:text-slate-400">
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

            {/* Row 2: playback speed */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-slate-400 mr-1">Speed</span>
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => (
                <button
                  key={rate}
                  onClick={() => {
                    setPlaybackRate(rate);
                    if (audioRef.current) audioRef.current.playbackRate = rate;
                  }}
                  className={`px-1.5 py-0.5 text-[10px] font-semibold rounded transition ${
                    playbackRate === rate
                      ? "bg-violet-600 text-white"
                      : "text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                  }`}
                >
                  {rate}×
                </button>
              ))}
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
