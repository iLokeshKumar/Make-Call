"use client";

type StatusPoint = {
  day: string;
  status: string;
  count: number;
};

type Props = {
  rows: StatusPoint[];
  compact?: boolean;
  limitDays?: number;
};

const STATUS_COLORS = ["#8b5cf6", "#06b6d4", "#34d399", "#f59e0b", "#f87171", "#a78bfa"];

export default function CampaignStatusTimelineChart({ rows, compact = false, limitDays }: Props) {
  const grouped = new Map<string, StatusPoint[]>();
  for (const row of rows) {
    const list = grouped.get(row.day) ?? [];
    list.push(row);
    grouped.set(row.day, list);
  }

  const days = [...grouped.keys()].sort();
  const visibleDays = typeof limitDays === "number" ? days.slice(-limitDays) : days;

  if (visibleDays.length === 0) {
    return <p className="text-sm text-slate-400">No status data available.</p>;
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {visibleDays.map((day) => {
        const items = (grouped.get(day) ?? []).slice().sort((left, right) => right.count - left.count);
        const total = items.reduce((sum, item) => sum + item.count, 0);
        return (
          <div key={day} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className={compact ? "text-[11px] font-medium text-slate-200" : "text-sm font-medium text-slate-200"}>
                {day}
              </span>
              <span className="text-[11px] text-slate-500">{total} total</span>
            </div>
            <div className="space-y-2">
              {items.map((item, index) => {
                const width = total > 0 ? Math.max((item.count / total) * 100, item.count > 0 ? 6 : 0) : 0;
                return (
                  <div key={`${day}-${item.status}`} className="flex items-center gap-3">
                    <span className={compact ? "w-20 text-[11px] text-slate-400" : "w-24 text-xs text-slate-400"}>
                      {item.status}
                    </span>
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-white/10">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${width}%`, backgroundColor: STATUS_COLORS[index % STATUS_COLORS.length] }}
                      />
                    </div>
                    <span className={compact ? "w-10 text-right text-[11px] font-semibold text-slate-200" : "w-12 text-right text-xs font-semibold text-slate-200"}>
                      {item.count}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
