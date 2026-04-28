import clsx from "clsx";

type ActivityItem = {
  id: string;
  title: string;
  subtitle: string;
  timestamp?: string | null;
  status?: "new" | "pending" | "success" | "warning";
};

type RecentActivityProps = {
  items: ActivityItem[];
  loading?: boolean;
};

function formatDate(value?: string | null) {
  if (!value) return "Just now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Just now";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function RecentActivity({ items, loading = false }: RecentActivityProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10">
      <div className="mb-5">
        <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Recent activity</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">A timeline view is how the frontend makes the backend audit trail actually useful.</p>
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            Loading timeline...
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            No activity has been recorded yet.
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white/80 p-4 dark:border-white/10 dark:bg-slate-900/30">
              <div className="flex gap-3">
                <div
                  className={clsx(
                    "mt-1 h-2.5 w-2.5 rounded-full",
                    item.status === "success" && "bg-emerald-500",
                    item.status === "warning" && "bg-amber-500",
                    item.status === "pending" && "bg-blue-500",
                    (!item.status || item.status === "new") && "bg-violet-500"
                  )}
                />
                <div>
                  <p className="font-medium text-slate-900 dark:text-white">{item.title}</p>
                  <p className="text-sm text-slate-600 dark:text-slate-300">{item.subtitle}</p>
                </div>
              </div>
              <span className="whitespace-nowrap text-xs text-slate-400 dark:text-slate-500">{formatDate(item.timestamp)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
