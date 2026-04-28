"use client";

import { useEffect, useRef, useState } from "react";

const WS_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060")
    .replace(/^http/, "ws");

type SentimentData = {
  score: number;
  label: "positive" | "neutral" | "negative" | "objection";
  snippet: string;
  interaction_id?: string;
  type?: string;
};

type Props = {
  interactionId: number | string;
  /** Called when the WebSocket closes unexpectedly */
  onDisconnect?: () => void;
};

const LABEL_CONFIG: Record<
  SentimentData["label"],
  { text: string; arcColor: string; bgClass: string; textClass: string }
> = {
  positive: {
    text: "Positive",
    arcColor: "#10b981",
    bgClass: "bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20",
    textClass: "text-emerald-700 dark:text-emerald-300",
  },
  neutral: {
    text: "Neutral",
    arcColor: "#6366f1",
    bgClass: "bg-violet-50 border-violet-200 dark:bg-violet-500/10 dark:border-violet-500/20",
    textClass: "text-violet-700 dark:text-violet-300",
  },
  negative: {
    text: "Negative",
    arcColor: "#ef4444",
    bgClass: "bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/20",
    textClass: "text-red-700 dark:text-red-300",
  },
  objection: {
    text: "Objection",
    arcColor: "#f59e0b",
    bgClass: "bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20",
    textClass: "text-amber-700 dark:text-amber-300",
  },
};

/** SVG arc gauge: draws a semicircle fill based on score 0-100 */
function ArcGauge({ score, color }: { score: number; color: string }) {
  const R = 44;
  const cx = 56;
  const cy = 56;
  const circumference = Math.PI * R; // half-circle circumference
  const filled = (score / 100) * circumference;
  const gap = circumference - filled;

  // Path: start at left (180°) and arc clockwise to right (0°)
  const startX = cx - R;
  const startY = cy;
  const endX = cx + R;
  const endY = cy;

  return (
    <svg viewBox="0 0 112 60" className="w-28 overflow-visible">
      {/* Track */}
      <path
        d={`M ${startX} ${startY} A ${R} ${R} 0 0 1 ${endX} ${endY}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="8"
        strokeLinecap="round"
        className="text-slate-200 dark:text-slate-700"
      />
      {/* Fill */}
      <path
        d={`M ${startX} ${startY} A ${R} ${R} 0 0 1 ${endX} ${endY}`}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={`${filled} ${gap}`}
        style={{ transition: "stroke-dasharray 0.5s ease" }}
      />
      {/* Score label */}
      <text
        x={cx}
        y={cy - 4}
        textAnchor="middle"
        fontSize="15"
        fontWeight="700"
        fill={color}
      >
        {score}
      </text>
    </svg>
  );
}

export default function SentimentGauge({ interactionId, onDisconnect }: Props) {
  const [sentiment, setSentiment] = useState<SentimentData>({
    score: 50,
    label: "neutral",
    snippet: "Waiting for speech...",
  });
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!interactionId) return;

    const url = `${WS_BASE}/ws/sentiment/${interactionId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SentimentData;
        if (data.type === "ping") return;
        setSentiment(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      onDisconnect?.();
    };

    ws.onerror = () => ws.close();

    return () => {
      ws.close();
    };
  }, [interactionId, onDisconnect]);

  const cfg = LABEL_CONFIG[sentiment.label] ?? LABEL_CONFIG.neutral;

  return (
    <div className={`rounded-2xl border p-4 ${cfg.bgClass} flex flex-col gap-3`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected ? "bg-emerald-400 animate-pulse" : "bg-slate-400"
            }`}
          />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Live Sentiment
          </span>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${cfg.textClass}`}>
          {cfg.text}
        </span>
      </div>

      <div className="flex items-center gap-4">
        <ArcGauge score={sentiment.score} color={cfg.arcColor} />
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">Last heard</p>
          <p className={`text-sm font-medium truncate ${cfg.textClass}`}>
            "{sentiment.snippet}"
          </p>
        </div>
      </div>
    </div>
  );
}
