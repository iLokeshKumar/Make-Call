type RequirementData = {
  use_case?: string | null;
  budget_range?: string | null;
  timeline?: string | null;
  decision_maker?: string | null;
  pain_points?: string | null;
  required_products?: string | null;
};

type QualificationCardProps = {
  qualificationStatus?: string | null;
  requirement?: RequirementData | null;
};

function humanize(value?: string | null) {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function QualificationCard({ qualificationStatus, requirement }: QualificationCardProps) {
  const items = [
    { label: "Use case", value: requirement?.use_case },
    { label: "Budget", value: requirement?.budget_range },
    { label: "Timeline", value: requirement?.timeline },
    { label: "Decision maker", value: requirement?.decision_maker },
    { label: "Pain points", value: requirement?.pain_points },
    { label: "Required products", value: requirement?.required_products },
  ];

  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Qualification + AI insights</h2>
        <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-700 dark:bg-violet-500/10 dark:text-violet-200">
          {humanize(qualificationStatus || "unqualified")}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/30">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{item.label}</p>
            <p className="mt-1 text-sm text-slate-900 dark:text-slate-200">{item.value || "Not captured yet"}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
