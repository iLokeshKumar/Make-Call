"use client";

import clsx from "clsx";

type ConversionRow = {
  campaign_id?: number;
  name: string;
  responded: number;
  sent: number;
  conversion_rate: number;
};

type Props = {
  rows: ConversionRow[];
  compact?: boolean;
  limit?: number;
};

function rateClass(rate: number) {
  if (rate >= 30) return "text-emerald-400";
  if (rate >= 10) return "text-amber-400";
  return "text-rose-400";
}

export default function CampaignConversionChart({ rows, compact = false, limit }: Props) {
  const items = typeof limit === "number" ? rows.slice(0, limit) : rows;
  const maxRate = Math.max(...items.map((row) => row.conversion_rate), 1);

  if (items.length === 0) {
    return <p className="text-sm text-slate-400">No campaign data</p>;
  }

  return (
    <div className={clsx("space-y-3", compact && "space-y-2")}>
      {items.map((row) => {
        const width = Math.max((row.conversion_rate / maxRate) * 100, row.conversion_rate > 0 ? 4 : 0);
        return (
          <div key={row.campaign_id ?? row.name} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-100">{row.name}</p>
                <p className="text-xs text-slate-500">
                  {row.responded} responded / {row.sent} sent
                </p>
              </div>
              <span className={clsx("shrink-0 text-sm font-semibold", rateClass(row.conversion_rate))}>
                {row.conversion_rate.toFixed(1)}%
              </span>
            </div>
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/8">
              <div
                className="h-full rounded-full bg-gradient-to-r from-violet-500 to-cyan-400 transition-all duration-700"
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
