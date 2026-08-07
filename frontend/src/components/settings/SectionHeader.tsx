"use client";
import { ArrowLeft, Save, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { SectionDef } from "./SettingsCard";
import clsx from "clsx";

type Props = {
  section: SectionDef;
  onBack: () => void;
  onSave?: () => void;
  saving?: boolean;
  saveSuccess?: boolean;
  saveError?: string | null;
  hideSave?: boolean;
};

export default function SectionHeader({
  section,
  onBack,
  onSave,
  saving,
  saveSuccess,
  saveError,
  hideSave,
}: Props) {
  const Icon = section.icon;

  return (
    <div
      className={clsx(
        "sticky top-0 z-20",
        "bg-white/90 dark:bg-slate-950/90 backdrop-blur-md",
        "border-b border-slate-200/70 dark:border-white/8",
        "px-0 py-3 mb-6"
      )}
    >
      <div className="flex items-center justify-between gap-4">
        {/* Left: back button + section identity */}
        <div className="flex items-center gap-3 min-w-0">
          {/* Back */}
          <button
            onClick={onBack}
            className={clsx(
              "flex-shrink-0 flex items-center justify-center h-8 w-8 rounded-xl",
              "bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700",
              "text-slate-600 dark:text-slate-400 transition-colors"
            )}
            aria-label="Back to Settings"
          >
            <ArrowLeft size={15} />
          </button>

          {/* Divider */}
          <div className="h-5 w-px bg-slate-200 dark:bg-slate-700 flex-shrink-0" />

          {/* Icon + label */}
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={clsx(
                "flex-shrink-0 h-9 w-9 rounded-xl flex items-center justify-center shadow-sm",
                "bg-gradient-to-br",
                section.iconGradient
              )}
            >
              <Icon size={16} className="text-white" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-slate-400 dark:text-slate-500 leading-none mb-0.5">
                Settings
              </p>
              <h1 className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate leading-none">
                {section.label}
              </h1>
            </div>
          </div>
        </div>

        {/* Right: save controls */}
        {!hideSave && (
          <div className="flex items-center gap-3 flex-shrink-0">
            {saveError && (
              <span className="hidden sm:flex items-center gap-1.5 text-xs text-red-500 font-medium max-w-[180px] truncate">
                <AlertCircle size={12} /> {saveError}
              </span>
            )}
            {saveSuccess && (
              <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 font-semibold">
                <CheckCircle2 size={13} /> Saved
              </span>
            )}
            <button
              onClick={onSave}
              disabled={saving}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-colors",
                "bg-violet-600 hover:bg-violet-700 text-white shadow-sm shadow-violet-500/25",
                "disabled:opacity-60 disabled:cursor-not-allowed"
              )}
            >
              {saving ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Save size={13} />
              )}
              Save
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
