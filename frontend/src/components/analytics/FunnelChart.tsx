"use client";

import clsx from "clsx";

type FunnelItem = {
  status: string;
  count: number;
  percent: number;
};

type Props = {
  items: FunnelItem[];
  compact?: boolean;
};

const DEFAULT_COLORS = ["#818cf8", "#60a5fa", "#34d399", "#fbbf24", "#a78bfa", "#f87171"];

export default function FunnelChart({ items, compact = false }: Props) {
  const maxCount = Math.max(...items.map((item) => item.count), 1);

  if (items.length === 0) {
    return <p className="text-sm text-slate-400">No funnel data</p>;
  }

  return (
    <div className={clsx("space-y-3", compact && "space-y-2")}>
      {items.map((item, index) => {
        const width = Math.max((item.count / maxCount) * 100, item.count > 0 ? 6 : 0);
        const color = DEFAULT_COLORS[index % DEFAULT_COLORS.length];
        const indent = compact ? index * 8 : index * 12;
        return (
          <div key={item.status} className="flex items-center gap-3" style={{ paddingLeft: indent }}>
            <span className={clsx("shrink-0 text-slate-400", compact ? "w-20 text-[11px]" : "w-24 text-xs")}>
              {item.status}
            </span>
            <div className="h-5 flex-1 overflow-hidden rounded-full bg-white/8">
              <div
                className="flex h-full items-center rounded-full px-2 transition-all duration-700"
                style={{ width: `${width}%`, backgroundColor: `${color}99` }}
              />
            </div>
            <span className={clsx("w-14 shrink-0 text-right font-mono font-semibold", compact ? "text-[11px]" : "text-xs")} style={{ color }}>
              {item.count.toLocaleString()}
            </span>
            <span className={clsx("w-12 shrink-0 text-right font-mono text-slate-500", compact ? "text-[10px]" : "text-[11px]")}>
              {item.percent.toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
