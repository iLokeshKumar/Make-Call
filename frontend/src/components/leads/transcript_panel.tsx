import { Check, Copy, MessageSquareText } from "lucide-react";
import { useState } from "react";

type TranscriptPanelProps = {
  transcript?: string | null;
};

type TranscriptLine = {
  speaker: "rio" | "user" | "system";
  text: string;
};

function parseTranscript(transcript?: string | null): TranscriptLine[] {
  if (!transcript) return [];

  return transcript
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.toLowerCase().startsWith("rio:")) {
        return { speaker: "rio" as const, text: line.replace(/^rio:\s*/i, "") };
      }
      if (line.toLowerCase().startsWith("user:")) {
        return { speaker: "user" as const, text: line.replace(/^user:\s*/i, "") };
      }
      return { speaker: "system" as const, text: line };
    });
}

export default function TranscriptPanel({ transcript }: TranscriptPanelProps) {
  const items = parseTranscript(transcript);
  const [copied, setCopied] = useState(false);

  async function copyTranscript() {
    if (!transcript) return;
    try {
      await navigator.clipboard.writeText(transcript);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy transcript", error);
    }
  }

  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Transcript</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">This panel gives reps quick context immediately after a voice interaction.</p>
        </div>
        <button
          type="button"
          onClick={copyTranscript}
          className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition-colors ${
            copied
              ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300"
              : "border-slate-200 text-slate-700 dark:border-white/10 dark:text-slate-200"
          }`}
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
          <MessageSquareText className="mx-auto mb-3 h-5 w-5" />
          No transcript has been saved for this lead yet.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item, index) => (
            <div
              key={`${item.speaker}-${index}`}
              className={item.speaker === "rio" ? "ml-8 rounded-2xl bg-violet-50 p-3 dark:bg-violet-500/10" : item.speaker === "user" ? "mr-8 rounded-2xl bg-slate-100 p-3 dark:bg-slate-800" : "rounded-2xl border border-slate-200 p-3 dark:border-white/10"}
            >
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                {item.speaker === "rio" ? "Rio" : item.speaker === "user" ? "Customer" : "System"}
              </p>
              <p className="text-sm text-slate-800 dark:text-slate-100">{item.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
