import Link from "next/link";
import clsx from "clsx";
import { ChevronRight, Clock3, PhoneCall } from "lucide-react";

type TaskItem = {
  id: number;
  leadId?: number;
  leadName: string;
  status: string;
  scheduledAt?: string | null;
  note?: string | null;
};

type TodaysCallTaskProps = {
  items: TaskItem[];
  loading?: boolean;
};

function formatDate(value?: string | null) {
  if (!value) return "No due time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No due time";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function TodaysCallTask({ items, loading = false }: TodaysCallTaskProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Today’s call tasks</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">This is the operational view that makes the backend task engine useful to reps.</p>
        </div>
        <PhoneCall className="h-5 w-5 text-violet-500" />
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            Loading call queue...
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            No pending call tasks right now.
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="rounded-xl border border-slate-200 bg-white/80 p-4 dark:border-white/10 dark:bg-slate-900/30">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-slate-900 dark:text-white">{item.leadName}</h3>
                    <span
                      className={clsx(
                        "rounded-full px-2.5 py-1 text-xs font-medium",
                        item.status === "dialing" && "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200",
                        item.status === "queued" && "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200",
                        item.status === "pending" && "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                      )}
                    >
                      {item.status}
                    </span>
                  </div>
                  <p className="mt-1 inline-flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                    <Clock3 className="h-4 w-4" /> {formatDate(item.scheduledAt)}
                  </p>
                  {item.note && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{item.note}</p>}
                </div>

                <Link
                  href={item.leadId ? `/leads/${item.leadId}` : "/leads"}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-violet-300 hover:text-violet-700 dark:border-white/10 dark:text-slate-200"
                >
                  Open <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
