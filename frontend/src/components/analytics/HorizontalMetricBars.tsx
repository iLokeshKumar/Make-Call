"use client";

type MetricRow = {
  label: string;
  value: number;
  color?: string;
  suffix?: string;
};

type Props = {
  rows: MetricRow[];
  compact?: boolean;
};

const COLORS = ["#8b5cf6", "#06b6d4", "#34d399", "#f59e0b", "#f87171", "#a78bfa"];

export default function HorizontalMetricBars({ rows, compact = false }: Props) {
  const maxValue = Math.max(...rows.map((row) => row.value), 1);

  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">No data available.</p>;
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {rows.map((row, index) => {
        const width = Math.max((row.value / maxValue) * 100, row.value > 0 ? 4 : 0);
        const color = row.color ?? COLORS[index % COLORS.length];
        return (
          <div key={row.label} className="flex items-center gap-3">
            <span className={compact ? "w-20 text-[11px] text-slate-400 capitalize" : "w-24 text-xs text-slate-400 capitalize"}>
              {row.label}
            </span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{ width: `${width}%`, backgroundColor: color }}
              />
            </div>
            <span className={compact ? "w-12 text-right text-[11px] font-semibold text-slate-200" : "w-14 text-right text-xs font-semibold text-slate-200"}>
              {row.value.toLocaleString()}{row.suffix ?? ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
