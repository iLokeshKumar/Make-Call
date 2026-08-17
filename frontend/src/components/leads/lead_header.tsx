import { Mail, Phone, Sparkles, Trash2 } from "lucide-react";

type LeadHeaderProps = {
  name: string;
  phone?: string | null;
  email?: string | null;
  status?: string | null;
  qualificationStatus?: string | null;
  source?: string | null;
  onCall?: () => void;
  onReviewAIInsights?: () => void;
  onDelete?: () => void;
};

function humanize(value?: string | null) {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function LeadHeader({
  name,
  phone,
  email,
  status,
  qualificationStatus,
  source,
  onCall,
  onReviewAIInsights,
  onDelete,
}: LeadHeaderProps) {
  return (
    <div className="rounded-3xl glass border border-white/40 p-6 dark:border-white/10">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">Lead 360</p>
          <h1 className="mt-1 text-3xl font-bold text-slate-900 dark:text-white">{name}</h1>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {status && <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">{humanize(status)}</span>}
            {qualificationStatus && <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-700 dark:bg-violet-500/10 dark:text-violet-200">{humanize(qualificationStatus)}</span>}
            {source && <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">{humanize(source)}</span>}
          </div>

          <div className="mt-4 flex flex-wrap gap-4 text-sm text-slate-600 dark:text-slate-300">
            {phone && <span className="inline-flex items-center gap-2"><Phone className="h-4 w-4" /> {phone}</span>}
            {email && <span className="inline-flex items-center gap-2"><Mail className="h-4 w-4" /> {email}</span>}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onCall}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white"
          >
            <Phone className="h-4 w-4" /> Call now
          </button>
          <button
            type="button"
            onClick={onReviewAIInsights}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 dark:border-white/10 dark:text-slate-200"
          >
            <Sparkles className="h-4 w-4" /> Review AI insights
          </button>
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              className="inline-flex items-center gap-2 rounded-xl border border-red-200 px-4 py-2.5 text-sm font-semibold text-red-700 dark:border-red-500/20 dark:text-red-300"
            >
              <Trash2 className="h-4 w-4" /> Delete lead
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
