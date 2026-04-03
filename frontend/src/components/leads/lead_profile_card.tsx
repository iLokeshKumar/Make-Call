type LeadProfileCardProps = {
  phone?: string | null;
  email?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  industry?: string | null;
  website?: string | null;
  notes?: string | null;
};

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-b-0 dark:border-white/5">
      <span className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-sm text-right text-slate-900 dark:text-slate-200">{value || "—"}</span>
    </div>
  );
}

export default function LeadProfileCard(props: LeadProfileCardProps) {
  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">Lead profile</h2>
      <div className="space-y-1">
        <DetailRow label="Phone" value={props.phone} />
        <DetailRow label="Email" value={props.email} />
        <DetailRow label="City" value={props.city} />
        <DetailRow label="State" value={props.state} />
        <DetailRow label="Country" value={props.country} />
        <DetailRow label="Industry" value={props.industry} />
        <DetailRow label="Website" value={props.website} />
      </div>

      {props.notes && (
        <div className="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
          {props.notes}
        </div>
      )}
    </div>
  );
}
