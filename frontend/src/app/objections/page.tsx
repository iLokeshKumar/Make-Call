"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, Edit3, Plus, Save, Trash2, X, Loader2, Shield, TrendingUp } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Objection = {
  id: number;
  objection_key: string;
  objection_text: string;
  category: string;
  rebuttal?: string | null;
  frequency_count: number;
  is_active: boolean;
};

const CATEGORY_CONFIG: Record<string, { label: string; cls: string }> = {
  price:      { label: "Price",      cls: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  competitor: { label: "Competitor", cls: "bg-orange-100 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300" },
  timing:     { label: "Timing",     cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  need:       { label: "Need",       cls: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300" },
  general:    { label: "General",    cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
};

const CATEGORIES = ["price", "competitor", "timing", "need", "general"];

function CategoryPill({ category }: { category: string }) {
  const cfg = CATEGORY_CONFIG[category] ?? CATEGORY_CONFIG.general;
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

export default function ObjectionsPage() {
  const { token, sessionTimeout } = useAuth();
  const [objections, setObjections] = useState<Objection[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [editId, setEditId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Partial<Objection>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [newForm, setNewForm] = useState({
    objection_key: "",
    objection_text: "",
    category: "general",
    rebuttal: "",
  });
  const [creating, setCreating] = useState(false);

  const fetchObjections = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = filterCategory !== "all" ? `?category=${filterCategory}` : "";
      const res = await fetch(`${API_BASE}/crm/objections${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load objections");
      const data = await res.json();
      setObjections(data.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [token, sessionTimeout, filterCategory]);

  useEffect(() => { fetchObjections(); }, [fetchObjections]);

  async function handleSaveEdit(id: number) {
    if (!token) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/crm/objections/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          objection_text: editDraft.objection_text,
          category: editDraft.category,
          rebuttal: editDraft.rebuttal || null,
          is_active: editDraft.is_active,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Update failed");
      const updated = await res.json();
      setObjections((prev) => prev.map((o) => (o.id === id ? updated : o)));
      setEditId(null);
      setMessage("Saved successfully.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!token || !window.confirm("Delete this objection entry?")) return;
    try {
      const res = await fetch(`${API_BASE}/crm/objections/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      setObjections((prev) => prev.filter((o) => o.id !== id));
    } catch {
      setMessage("Delete failed.");
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newForm.objection_key || !newForm.objection_text) return;
    setCreating(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/crm/objections`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          objection_key: newForm.objection_key.toLowerCase().trim(),
          objection_text: newForm.objection_text.trim(),
          category: newForm.category,
          rebuttal: newForm.rebuttal.trim() || null,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.detail || "Create failed");
      }
      await fetchObjections();
      setShowCreate(false);
      setNewForm({ objection_key: "", objection_text: "", category: "general", rebuttal: "" });
      setMessage("Objection added to library.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Create failed.");
    } finally {
      setCreating(false);
    }
  }

  const displayed = filterCategory === "all"
    ? objections
    : objections.filter((o) => o.category === filterCategory);

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
          AI Sales Intelligence
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
          <span className="gradient-text">Objection</span> Library
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          Auto-populated from call transcripts. Edit rebuttals to train Rio to handle
          objections more effectively.
        </p>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Total objections", value: objections.length, icon: BookOpen },
          { label: "With rebuttals", value: objections.filter((o) => o.rebuttal).length, icon: Shield },
          { label: "Active", value: objections.filter((o) => o.is_active).length, icon: TrendingUp },
          {
            label: "Most common",
            value: objections[0]
              ? `${objections[0].frequency_count}×`
              : "—",
            icon: TrendingUp,
          },
        ].map(({ label, value, icon: Icon }) => (
          <div
            key={label}
            className="rounded-2xl glass border border-white/40 p-4 dark:border-white/10"
          >
            <div className="flex items-center gap-2 text-violet-500 mb-1">
              <Icon className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                {label}
              </span>
            </div>
            <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {["all", ...CATEGORIES].map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCategory(cat)}
              className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
                filterCategory === cat
                  ? "bg-violet-600 text-white shadow"
                  : "bg-slate-100 text-slate-600 hover:bg-violet-100 hover:text-violet-700 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {cat === "all" ? "All" : CATEGORY_CONFIG[cat]?.label ?? cat}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20"
        >
          {showCreate ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showCreate ? "Cancel" : "Add manually"}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <form
          onSubmit={handleCreate}
          className="rounded-2xl glass border border-violet-200 p-5 dark:border-violet-500/20 space-y-4"
        >
          <h3 className="font-semibold text-slate-900 dark:text-white">Add new objection</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Objection key (canonical, lowercase)
              </label>
              <input
                value={newForm.objection_key}
                onChange={(e) => setNewForm((f) => ({ ...f, objection_key: e.target.value }))}
                placeholder="e.g. too expensive"
                required
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Category
              </label>
              <select
                value={newForm.category}
                onChange={(e) => setNewForm((f) => ({ ...f, category: e.target.value }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{CATEGORY_CONFIG[c]?.label ?? c}</option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Objection text (as spoken by the prospect)
              </label>
              <input
                value={newForm.objection_text}
                onChange={(e) => setNewForm((f) => ({ ...f, objection_text: e.target.value }))}
                placeholder="e.g. Your pricing is too high for our budget"
                required
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Rebuttal (what Rio should say in response)
              </label>
              <textarea
                value={newForm.rebuttal}
                onChange={(e) => setNewForm((f) => ({ ...f, rebuttal: e.target.value }))}
                placeholder="e.g. I understand budget is a concern. We offer flexible payment plans and the ROI typically pays back within 3 months."
                rows={3}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {creating ? "Adding..." : "Add to library"}
          </button>
        </form>
      )}

      {message && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-2 text-sm text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-300">
          {message}
        </div>
      )}

      {/* Objection list */}
      {loading ? (
        <div className="flex items-center justify-center py-12 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading objection library...
        </div>
      ) : displayed.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          <BookOpen className="mx-auto mb-3 h-8 w-8 opacity-40" />
          <p className="font-medium">No objections yet.</p>
          <p className="mt-1 text-sm">
            Objections are auto-extracted after every call. You can also add them manually above.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {displayed.map((obj) => (
            <div
              key={obj.id}
              className={`rounded-2xl border bg-white/80 p-5 transition dark:bg-slate-900/40 ${
                obj.is_active
                  ? "border-slate-200 dark:border-white/10"
                  : "border-slate-100 opacity-60 dark:border-white/5"
              }`}
            >
              {editId === obj.id ? (
                /* ── Edit mode ── */
                <div className="space-y-3">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-xs font-semibold text-slate-500">Objection text</label>
                      <input
                        value={editDraft.objection_text ?? ""}
                        onChange={(e) => setEditDraft((d) => ({ ...d, objection_text: e.target.value }))}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-semibold text-slate-500">Category</label>
                      <select
                        value={editDraft.category ?? "general"}
                        onChange={(e) => setEditDraft((d) => ({ ...d, category: e.target.value }))}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                      >
                        {CATEGORIES.map((c) => (
                          <option key={c} value={c}>{CATEGORY_CONFIG[c]?.label ?? c}</option>
                        ))}
                      </select>
                    </div>
                    <div className="sm:col-span-2">
                      <label className="mb-1 block text-xs font-semibold text-slate-500">Rebuttal</label>
                      <textarea
                        value={editDraft.rebuttal ?? ""}
                        onChange={(e) => setEditDraft((d) => ({ ...d, rebuttal: e.target.value }))}
                        rows={3}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => handleSaveEdit(obj.id)}
                      disabled={saving}
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      <Save className="h-3.5 w-3.5" />
                      {saving ? "Saving..." : "Save"}
                    </button>
                    <button
                      onClick={() => setEditId(null)}
                      className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                /* ── Read mode ── */
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-900 dark:text-white">
                        "{obj.objection_text}"
                      </span>
                      <CategoryPill category={obj.category} />
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        {obj.frequency_count}× raised
                      </span>
                      {!obj.is_active && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-400 dark:bg-slate-800">
                          Inactive
                        </span>
                      )}
                    </div>
                    {obj.rebuttal ? (
                      <p className="text-sm text-slate-600 dark:text-slate-400">
                        <span className="font-medium text-violet-600 dark:text-violet-400">Rebuttal: </span>
                        {obj.rebuttal}
                      </p>
                    ) : (
                      <p className="text-xs italic text-slate-400 dark:text-slate-500">
                        No rebuttal set — click Edit to add one.
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      onClick={() => { setEditId(obj.id); setEditDraft({ ...obj }); }}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:border-violet-400 hover:text-violet-700 dark:border-white/10 dark:text-slate-300 transition"
                    >
                      <Edit3 className="h-3.5 w-3.5" /> Edit
                    </button>
                    <button
                      onClick={() => handleDelete(obj.id)}
                      className="rounded-xl border border-red-200 px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 transition"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
