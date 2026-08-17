import { CalendarClock, ClipboardCheck } from "lucide-react";

type NextActionCardProps = {
  nextAction?: string | null;
  dueAt?: string | null;
  onMarkReviewed?: () => void;
};

function humanize(value?: string | null) {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDate(value?: string | null) {
  if (!value) return "No due date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No due date";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function NextActionCard({ nextAction, dueAt, onMarkReviewed }: NextActionCardProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">Next action</h2>

      <div className="space-y-3">
        <div className="rounded-xl bg-violet-50 p-3 dark:bg-violet-500/10">
          <p className="text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-200">Recommended move</p>
          <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{humanize(nextAction || "none")}</p>
        </div>

        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <CalendarClock className="h-4 w-4" /> {formatDate(dueAt)}
        </div>

        <button onClick={onMarkReviewed}
          type="button"
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 dark:border-white/10 dark:text-slate-200"
        >
          <ClipboardCheck className="h-4 w-4" /> Mark reviewed
        </button>
      </div>
    </div>
  );
}
