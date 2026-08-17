import { ArrowUpRight, LucideIcon } from "lucide-react";
import clsx from "clsx";

type MetricCardProps = {
  title: string;
  value: string;
  helper: string;
  icon: LucideIcon;
  tone?: "violet" | "blue" | "emerald" | "orange";
};

const toneStyles = {
  violet: {
    icon: "from-violet-600 to-fuchsia-600",
    ring: "shadow-violet-500/30",
  },
  blue: {
    icon: "from-blue-600 to-cyan-600",
    ring: "shadow-blue-500/30",
  },
  emerald: {
    icon: "from-emerald-600 to-teal-600",
    ring: "shadow-emerald-500/30",
  },
  orange: {
    icon: "from-orange-500 to-amber-600",
    ring: "shadow-orange-500/30",
  },
};

export default function MetricCard({ title, value, helper, icon: Icon, tone = "violet" }: MetricCardProps) {
  const styles = toneStyles[tone];

  return (
    <div className="group rounded-2xl glass border border-white/40 p-5 transition hover:-translate-y-0.5 hover:shadow-lg dark:border-white/10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-500 dark:text-slate-400">{title}</p>
          <p className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">{value}</p>
          <div className="mt-3 flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <ArrowUpRight className="h-3.5 w-3.5 text-emerald-500" />
            <span>{helper}</span>
          </div>
        </div>

        <div
          className={clsx(
            "flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-lg",
            styles.icon,
            styles.ring
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}
