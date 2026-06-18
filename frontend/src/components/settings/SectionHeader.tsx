"use client";
import { ChevronRight, Save, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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
        "sticky top-0 z-20 flex items-center justify-between gap-4",
        "bg-slate-50/90 dark:bg-slate-950/90 backdrop-blur-md",
        "border-b border-slate-200/60 dark:border-white/10",
        "px-0 py-4 mb-6"
      )}
    >
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 min-w-0">
        <button
          onClick={onBack}
          className="text-sm font-medium text-violet-600 dark:text-violet-400 hover:underline shrink-0"
        >
          Settings
        </button>
        <ChevronRight size={14} className="text-slate-400 shrink-0" />
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={clsx(
              "h-6 w-6 rounded-lg flex items-center justify-center bg-gradient-to-br shrink-0",
              section.iconGradient
            )}
          >
            <Icon size={12} className="text-white" />
          </div>
          <span className="text-sm font-semibold text-slate-900 dark:text-white truncate">
            {section.label}
          </span>
        </div>
      </div>

      {/* Save status + button */}
      {!hideSave && (
        <div className="flex items-center gap-3 shrink-0">
          {saveError && (
            <span className="text-xs text-red-500 font-medium max-w-[200px] truncate">
              {saveError}
            </span>
          )}
          {saveSuccess && (
            <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 font-semibold animate-in fade-in">
              <CheckCircle2 size={13} /> Saved
            </span>
          )}
          <Button
            onClick={onSave}
            disabled={saving}
            size="sm"
            className="bg-violet-600 hover:bg-violet-700 text-white rounded-xl shadow-lg shadow-violet-500/20 font-semibold"
          >
            {saving ? (
              <Loader2 size={14} className="animate-spin mr-1.5" />
            ) : (
              <Save size={14} className="mr-1.5" />
            )}
            Save
          </Button>
        </div>
      )}
    </div>
  );
}
