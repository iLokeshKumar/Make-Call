import clsx from "clsx";

type TimelineItem = {
  id: string;
  title: string;
  subtitle?: string | null;
  timestamp?: string | null;
  tone?: "violet" | "emerald" | "amber" | "blue";
};

type InteractionTimelineProps = {
  items: TimelineItem[];
};

function formatDate(value?: string | null) {
  if (!value) return "Just now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Just now";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function InteractionTimeline({ items }: InteractionTimelineProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">Activity timeline</h2>

      <div className="space-y-4">
        {items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            No interactions have been recorded for this lead yet.
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="flex gap-3">
              <div
                className={clsx(
                  "mt-1.5 h-2.5 w-2.5 rounded-full",
                  item.tone === "emerald" && "bg-emerald-500",
                  item.tone === "amber" && "bg-amber-500",
                  item.tone === "blue" && "bg-blue-500",
                  (!item.tone || item.tone === "violet") && "bg-violet-500"
                )}
              />
              <div className="flex-1 rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/30">
                <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                  <p className="font-medium text-slate-900 dark:text-white">{item.title}</p>
                  <span className="text-xs text-slate-400 dark:text-slate-500">{formatDate(item.timestamp)}</span>
                </div>
                {item.subtitle && <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.subtitle}</p>}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
