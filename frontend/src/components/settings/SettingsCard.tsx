"use client";
import { LucideIcon, Pin, PinOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import clsx from "clsx";

export type SectionDef = {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  group: string;
  iconGradient: string;
  adminOnly?: boolean;
  badge?: string;
};

type Props = {
  section: SectionDef;
  pinned: boolean;
  onClick: () => void;
  onTogglePin: (id: string) => void;
};

export default function SettingsCard({ section, pinned, onClick, onTogglePin }: Props) {
  const Icon = section.icon;

  return (
    <div
      onClick={onClick}
      className={clsx(
        "group relative flex flex-col gap-3 rounded-2xl border p-5 cursor-pointer",
        "bg-white/70 dark:bg-slate-800/60 backdrop-blur-md",
        "border-slate-200/70 dark:border-white/10",
        "transition-all duration-200",
        "hover:-translate-y-0.5 hover:shadow-lg hover:shadow-violet-500/10",
        "hover:border-violet-300/60 dark:hover:border-violet-500/30",
        pinned && "ring-1 ring-violet-400/40 dark:ring-violet-500/30"
      )}
    >
      {/* Pin button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onTogglePin(section.id);
        }}
        className={clsx(
          "absolute top-3 right-3 p-1 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity",
          pinned
            ? "opacity-100 text-violet-500 dark:text-violet-400"
            : "text-slate-400 dark:text-slate-500 hover:text-violet-500 dark:hover:text-violet-400"
        )}
        title={pinned ? "Unpin" : "Pin to top"}
      >
        {pinned ? <PinOff size={13} /> : <Pin size={13} />}
      </button>

      {/* Icon */}
      <div
        className={clsx(
          "flex h-11 w-11 items-center justify-center rounded-xl shrink-0",
          "bg-gradient-to-br",
          section.iconGradient
        )}
      >
        <Icon className="h-5 w-5 text-white" />
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0 pr-4">
        <p className="text-sm font-semibold text-slate-900 dark:text-white leading-tight">{section.label}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-snug line-clamp-2">{section.description}</p>
      </div>

      {section.badge && (
        <Badge variant="secondary" className="text-[10px] self-start">
          {section.badge}
        </Badge>
      )}
    </div>
  );
}
