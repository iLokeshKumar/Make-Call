"use client";

import React, { useMemo, useState } from "react";

type TrendPoint = {
  day: string;
  engine: string;
  avg_ms: number;
  turns: number;
};

type Props = {
  trend: TrendPoint[];
  formatMs: (value: number) => string;
  colorForEngine: (engine: string) => string;
};

type SeriesPoint = {
  day: string;
  value: number;
  turns: number;
  x: number;
  y: number;
};

type Series = {
  engine: string;
  color: string;
  points: SeriesPoint[];
};

const WIDTH = 960;
const HEIGHT = 320;
const MARGIN = { top: 16, right: 20, bottom: 36, left: 52 };
const TICK_COUNT = 5;

function buildPath(points: SeriesPoint[]) {
  if (points.length === 0) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function tickValues(maxValue: number) {
  const safeMax = Math.max(maxValue, 1);
  return Array.from({ length: TICK_COUNT }, (_, index) => {
    const ratio = index / (TICK_COUNT - 1);
    return safeMax - safeMax * ratio;
  });
}

export default function LatencyTrendChart({ trend, formatMs, colorForEngine }: Props) {
  const [hoveredDay, setHoveredDay] = useState<string | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  const chart = useMemo(() => {
    const days = [...new Set(trend.map((point) => point.day))].sort();
    const engines = [...new Set(trend.map((point) => point.engine))].sort();
    const maxValue = Math.max(...trend.map((point) => point.avg_ms), 1);
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

    const xForIndex = (index: number) => {
      if (days.length <= 1) return MARGIN.left + innerWidth / 2;
      return MARGIN.left + (innerWidth * index) / (days.length - 1);
    };

    const yForValue = (value: number) => MARGIN.top + innerHeight - (value / maxValue) * innerHeight;

    const valueMap = new Map<string, TrendPoint>();
    for (const point of trend) {
      valueMap.set(`${point.engine}__${point.day}`, point);
    }

    const series: Series[] = engines.map((engine) => ({
      engine,
      color: colorForEngine(engine),
      points: days.flatMap((day, index) => {
        const point = valueMap.get(`${engine}__${day}`);
        if (!point) return [];
        return [{
          day,
          value: point.avg_ms,
          turns: point.turns,
          x: xForIndex(index),
          y: yForValue(point.avg_ms),
        }];
      }),
    }));

    const activeDay = hoveredDay && days.includes(hoveredDay) ? hoveredDay : days.at(-1) ?? null;
    const activeIndex = activeDay ? days.indexOf(activeDay) : -1;
    const activePoints = activeDay
      ? series
          .map((entry) => ({
            engine: entry.engine,
            color: entry.color,
            point: entry.points.find((point) => point.day === activeDay) ?? null,
          }))
          .filter((entry) => entry.point)
          .sort((left, right) => (right.point?.value ?? 0) - (left.point?.value ?? 0))
      : [];

    return {
      days,
      maxValue,
      innerWidth,
      innerHeight,
      series,
      ticks: tickValues(maxValue),
      activeDay,
      activeIndex,
      activePoints,
      xForIndex,
      yForValue,
    };
  }, [colorForEngine, hoveredDay, trend]);

  const tickStride = Math.max(1, Math.ceil(chart.days.length / 6));

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">Latency Trend</p>
          <p className="text-xs text-slate-400">
            Multi-engine daily average turn latency with hover comparison.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-400">
          {chart.series.map((entry) => (
            <div key={entry.engine} className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
              <span className="font-mono">{entry.engine}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-slate-950/30">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="h-auto w-full"
            role="img"
            aria-label="Latency trend chart by engine"
            onMouseLeave={() => {
              setHoveredDay(null);
              setHoverX(null);
            }}
            onMouseMove={(event) => {
              const bounds = event.currentTarget.getBoundingClientRect();
              const ratio = (event.clientX - bounds.left) / Math.max(bounds.width, 1);
              const svgX = ratio * WIDTH;
              const clamped = Math.max(MARGIN.left, Math.min(WIDTH - MARGIN.right, svgX));
              const index = chart.days.length <= 1
                ? 0
                : Math.round(((clamped - MARGIN.left) / chart.innerWidth) * (chart.days.length - 1));
              setHoveredDay(chart.days[index] ?? null);
              setHoverX(chart.days[index] ? chart.xForIndex(index) : null);
            }}
          >
            {chart.ticks.map((tick) => {
              const y = chart.yForValue(tick);
              return (
                <g key={tick}>
                  <line
                    x1={MARGIN.left}
                    x2={WIDTH - MARGIN.right}
                    y1={y}
                    y2={y}
                    stroke="rgba(148,163,184,0.15)"
                    strokeDasharray="4 4"
                  />
                  <text x={MARGIN.left - 10} y={y + 4} fill="#94a3b8" fontSize="11" textAnchor="end">
                    {formatMs(tick)}
                  </text>
                </g>
              );
            })}

            {chart.series.map((entry) => (
              <g key={entry.engine}>
                <path
                  d={buildPath(entry.points)}
                  fill="none"
                  stroke={entry.color}
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {entry.points.map((point) => {
                  const active = point.day === chart.activeDay;
                  return (
                    <circle
                      key={`${entry.engine}-${point.day}`}
                      cx={point.x}
                      cy={point.y}
                      r={active ? 4.5 : 2.5}
                      fill={entry.color}
                      stroke={active ? "#e2e8f0" : "transparent"}
                      strokeWidth={active ? 1.5 : 0}
                      opacity={active ? 1 : 0.85}
                    />
                  );
                })}
              </g>
            ))}

            {chart.activeDay && hoverX !== null && (
              <line
                x1={hoverX}
                x2={hoverX}
                y1={MARGIN.top}
                y2={HEIGHT - MARGIN.bottom}
                stroke="rgba(226,232,240,0.35)"
                strokeDasharray="5 5"
              />
            )}

            {chart.days.map((day, index) => {
              if (index % tickStride !== 0 && index !== chart.days.length - 1) return null;
              return (
                <text
                  key={day}
                  x={chart.xForIndex(index)}
                  y={HEIGHT - 12}
                  fill={day === chart.activeDay ? "#e2e8f0" : "#94a3b8"}
                  fontSize="11"
                  textAnchor="middle"
                >
                  {day}
                </text>
              );
            })}
          </svg>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-950/30 p-3">
          <p className="text-[11px] uppercase tracking-[0.28em] text-slate-500">
            {chart.activeDay ?? "Latest"}
          </p>
          <div className="mt-3 space-y-2">
            {chart.activePoints.map(({ engine, color, point }) => (
              <div
                key={`${engine}-${point?.day}`}
                className="rounded-lg border border-white/5 bg-white/[0.03] px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-[11px]" style={{ color }}>
                    {engine}
                  </span>
                  <span className="text-sm font-semibold text-slate-100">
                    {point ? formatMs(point.value) : "-"}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                  <span>{point?.turns ?? 0} turns</span>
                  <span>{point ? `${Math.round((point.value / chart.maxValue) * 100)}% of max` : ""}</span>
                </div>
              </div>
            ))}
            {chart.activePoints.length === 0 && (
              <p className="text-sm text-slate-500">No trend points available.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
