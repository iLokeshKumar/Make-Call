import Link from "next/link";
import { BrainCircuit, Sparkles } from "lucide-react";

type RecommendationItem = {
  id: number;
  title: string;
  description: string;
  href: string;
  ctaLabel: string;
};

type AIRecommendationProps = {
  items: RecommendationItem[];
  loading?: boolean;
};

export default function AIRecommendation({ items, loading = false }: AIRecommendationProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10">
      <div className="mb-5 flex items-center gap-3">
        <div className="rounded-xl bg-violet-100 p-3 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
          <BrainCircuit className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">AI recommendations</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Frontend value = turning backend intelligence into a visible next step.</p>
        </div>
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
            Loading recommendations...
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="rounded-xl border border-slate-200 bg-white/80 p-4 dark:border-white/10 dark:bg-slate-900/30">
              <div className="mb-2 flex items-center gap-2 text-violet-600 dark:text-violet-300">
                <Sparkles className="h-4 w-4" />
                <span className="text-xs font-semibold uppercase tracking-[0.2em]">Suggested next move</span>
              </div>
              <h3 className="font-semibold text-slate-900 dark:text-white">{item.title}</h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.description}</p>
              <Link href={item.href} className="mt-3 inline-flex text-sm font-semibold text-violet-600 hover:text-violet-700 dark:text-violet-300">
                {item.ctaLabel}
              </Link>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
