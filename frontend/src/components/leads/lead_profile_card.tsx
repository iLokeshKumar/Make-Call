import { Pencil, X, Check, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

type EditableFields = {
  city?: string | null;
  state?: string | null;
  country?: string | null;
  pincode?: string | null;
  industry?: string | null;
  website?: string | null;
};

type LeadProfileCardProps = {
  phone?: string | null;
  email?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  pincode?: string | null;
  industry?: string | null;
  website?: string | null;
  notes?: string | null;
  onSave?: (fields: EditableFields) => Promise<void>;
  saving?: boolean;
  saveError?: string | null;
};

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 last:border-b-0 dark:border-white/5">
      <span className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-sm text-right text-slate-900 dark:text-slate-200">{value || "—"}</span>
    </div>
  );
}

function EditRow({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 py-2 last:border-b-0 dark:border-white/5">
      <span className="w-24 flex-shrink-0 text-sm font-medium text-slate-500 dark:text-slate-400">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "—"}
        className="flex-1 rounded-lg border border-slate-200 bg-white/60 px-2 py-1 text-right text-sm text-slate-900 outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100"
      />
    </div>
  );
}

export default function LeadProfileCard(props: LeadProfileCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Required<EditableFields>>({
    city: props.city ?? "",
    state: props.state ?? "",
    country: props.country ?? "",
    pincode: props.pincode ?? "",
    industry: props.industry ?? "",
    website: props.website ?? "",
  });

  useEffect(() => {
    if (!editing) {
      setDraft({
        city: props.city ?? "",
        state: props.state ?? "",
        country: props.country ?? "",
        pincode: props.pincode ?? "",
        industry: props.industry ?? "",
        website: props.website ?? "",
      });
    }
  }, [editing, props.city, props.state, props.country, props.pincode, props.industry, props.website]);

  async function handleSave() {
    if (!props.onSave) return;
    const payload: EditableFields = {};
    (Object.keys(draft) as (keyof EditableFields)[]).forEach((k) => {
      const trimmed = (draft[k] || "").trim();
      payload[k] = trimmed === "" ? null : trimmed;
    });
    await props.onSave(payload);
    setEditing(false);
  }

  const canEdit = !!props.onSave;

  return (
    <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Lead profile</h2>
        {canEdit && !editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:border-white/10 dark:text-slate-300"
          >
            <Pencil className="h-3 w-3" /> Edit
          </button>
        )}
        {editing && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleSave}
              disabled={props.saving}
              className="inline-flex items-center gap-1 rounded-lg bg-violet-600 px-2 py-1 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {props.saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              Save
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={props.saving}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:border-white/10 dark:text-slate-300 disabled:opacity-50"
            >
              <X className="h-3 w-3" /> Cancel
            </button>
          </div>
        )}
      </div>

      <div className="space-y-1">
        <DetailRow label="Phone" value={props.phone} />
        <DetailRow label="Email" value={props.email} />
        {editing ? (
          <>
            <EditRow label="City" value={draft.city ?? ""} onChange={(v) => setDraft({ ...draft, city: v })} />
            <EditRow label="State" value={draft.state ?? ""} onChange={(v) => setDraft({ ...draft, state: v })} />
            <EditRow label="Country" value={draft.country ?? ""} onChange={(v) => setDraft({ ...draft, country: v })} />
            <EditRow label="Pincode" value={draft.pincode ?? ""} onChange={(v) => setDraft({ ...draft, pincode: v })} placeholder="600016" />
            <EditRow label="Industry" value={draft.industry ?? ""} onChange={(v) => setDraft({ ...draft, industry: v })} />
            <EditRow label="Website" value={draft.website ?? ""} onChange={(v) => setDraft({ ...draft, website: v })} placeholder="https://..." />
          </>
        ) : (
          <>
            <DetailRow label="City" value={props.city} />
            <DetailRow label="State" value={props.state} />
            <DetailRow label="Country" value={props.country} />
            <DetailRow label="Pincode" value={props.pincode} />
            <DetailRow label="Industry" value={props.industry} />
            <DetailRow label="Website" value={props.website} />
          </>
        )}
      </div>

      {props.saveError && <p className="mt-3 text-xs font-medium text-amber-600 dark:text-amber-300">{props.saveError}</p>}

      {props.notes && !editing && (
        <div className="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
          {props.notes}
        </div>
      )}
    </div>
  );
}
