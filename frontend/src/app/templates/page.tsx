"use client";

import { useCallback, useEffect, useState } from "react";
import { FileText, Plus, Trash2, Eye, Save, X, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Template = {
  id: number;
  name: string;
  channel: string;
  subject?: string | null;
  body: string;
  variables_json?: Record<string, string> | null;
  created_at?: string;
};

type TemplateForm = {
  name: string;
  channel: string;
  subject: string;
  body: string;
};

const CHANNELS = ["call", "email", "whatsapp", "sms"] as const;

const CHANNEL_BADGE: Record<string, string> = {
  call: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  email: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  whatsapp: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  sms: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
};

const VARIABLES = ["{lead_name}", "{lead_phone}", "{company_name}", "{product_name}"];

const emptyForm: TemplateForm = { name: "", channel: "email", subject: "", body: "" };

function formatDate(iso?: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function ChannelBadge({ channel }: { channel: string }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium capitalize ${CHANNEL_BADGE[channel] ?? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"}`}>
      {channel}
    </span>
  );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl dark:bg-slate-700">
      <FileText className="h-4 w-4 text-violet-400" />
      {message}
      <button onClick={onClose} className="ml-2 text-slate-400 hover:text-white">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export default function TemplatesPage() {
  const { token, sessionTimeout } = useAuth();

  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState<TemplateForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);

  const [previewLeadId, setPreviewLeadId] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<{ subject?: string; body: string } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [toast, setToast] = useState<string | null>(null);

  const authHeaders = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  const fetchTemplates = useCallback(async () => {
    if (!token) { setLoading(false); return; }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/templates`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) setTemplates(await res.json());
    } finally { setLoading(false); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  const selectedTemplate = templates.find((t) => t.id === selectedId) ?? null;

  const selectTemplate = (tmpl: Template) => {
    setIsNew(false);
    setSelectedId(tmpl.id);
    setForm({
      name: tmpl.name,
      channel: tmpl.channel,
      subject: tmpl.subject ?? "",
      body: tmpl.body,
    });
    setPreview(null);
    setPreviewError(null);
    setPreviewLeadId("");
  };

  const startNew = () => {
    setIsNew(true);
    setSelectedId(null);
    setForm(emptyForm);
    setPreview(null);
    setPreviewError(null);
    setPreviewLeadId("");
  };

  const cancelEdit = () => {
    setIsNew(false);
    setSelectedId(null);
    setPreview(null);
    setPreviewError(null);
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.body.trim()) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        channel: form.channel,
        subject: form.channel === "email" ? (form.subject.trim() || undefined) : undefined,
        body: form.body.trim(),
      };
      const res = isNew
        ? await fetch(`${API_BASE}/templates`, { method: "POST", headers: authHeaders, body: JSON.stringify(body) })
        : await fetch(`${API_BASE}/templates/${selectedId}`, { method: "PUT", headers: authHeaders, body: JSON.stringify(body) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) {
        const saved: Template = await res.json();
        setToast(isNew ? "Template created" : "Template updated");
        setIsNew(false);
        setSelectedId(saved.id);
        await fetchTemplates();
      }
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleting(id);
    try {
      const res = await fetch(`${API_BASE}/templates/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) {
        setToast("Template deleted");
        if (selectedId === id) cancelEdit();
        await fetchTemplates();
      }
    } finally { setDeleting(null); }
  };

  const handlePreview = async () => {
    const leadId = Number(previewLeadId);
    if (!leadId || (!selectedId && !isNew)) return;
    const id = selectedId;
    if (!id) return;
    setPreviewing(true);
    setPreview(null);
    setPreviewError(null);
    try {
      const res = await fetch(`${API_BASE}/templates/${id}/render`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ lead_id: leadId }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) {
        setPreview(await res.json());
      } else {
        const data = await res.json().catch(() => ({}));
        setPreviewError(data.detail ?? "Preview failed");
      }
    } finally { setPreviewing(false); }
  };

  const isEditing = isNew || selectedId !== null;

  return (
    <div className="space-y-6 pb-8">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}

      {/* Header */}
      <div>
        <h1 className="text-4xl font-bold tracking-tight">
          <span className="gradient-text">Templates</span>
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
          Manage message templates across all channels
        </p>
      </div>

      <div className="flex gap-6 items-start flex-col lg:flex-row">
        {/* Left: Template list */}
        <div className="w-full lg:w-1/3 space-y-3">
          <button
            onClick={startNew}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20"
          >
            <Plus className="h-4 w-4" /> New Template
          </button>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-violet-500" />
            </div>
          ) : templates.length === 0 ? (
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 text-center">
              <FileText className="mx-auto h-8 w-8 text-slate-300 dark:text-slate-600 mb-2" />
              <p className="text-sm text-slate-400">No templates yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {templates.map((tmpl) => {
                const isSelected = selectedId === tmpl.id;
                return (
                  <button
                    key={tmpl.id}
                    onClick={() => selectTemplate(tmpl)}
                    className={`group relative w-full rounded-2xl border p-4 text-left transition ${
                      isSelected
                        ? "border-violet-400 bg-violet-50 dark:bg-violet-500/10 dark:border-violet-500/40"
                        : "border-white/40 dark:border-white/10 glass hover:border-violet-300 dark:hover:border-violet-500/30"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-semibold text-sm text-slate-800 dark:text-slate-100">
                          {tmpl.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-400">{formatDate(tmpl.created_at)}</p>
                      </div>
                      <div className="flex flex-col items-end gap-2 shrink-0">
                        <ChannelBadge channel={tmpl.channel} />
                        <button
                          onClick={(e) => handleDelete(tmpl.id, e)}
                          disabled={deleting === tmpl.id}
                          className="opacity-0 group-hover:opacity-100 transition-opacity rounded-lg p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10"
                          title="Delete template"
                        >
                          {deleting === tmpl.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="h-3.5 w-3.5" />
                          )}
                        </button>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Editor */}
        <div className="w-full lg:w-2/3">
          {!isEditing ? (
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-12 flex flex-col items-center justify-center text-center min-h-[320px]">
              <FileText className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
              <p className="text-slate-500 dark:text-slate-400 font-medium">
                Select a template to edit or create a new one
              </p>
            </div>
          ) : (
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-5">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                  {isNew ? "New Template" : `Edit — ${selectedTemplate?.name ?? ""}`}
                </h2>
                <button
                  onClick={cancelEdit}
                  className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/40 transition"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Name */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                  Template Name <span className="text-red-400">*</span>
                </label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="e.g. Welcome Email"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100"
                />
              </div>

              {/* Channel */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                  Channel
                </label>
                <div className="flex gap-2 flex-wrap">
                  {CHANNELS.map((ch) => (
                    <button
                      key={ch}
                      onClick={() => setForm((p) => ({ ...p, channel: ch }))}
                      className={`rounded-xl border px-4 py-2 text-sm font-medium capitalize transition ${
                        form.channel === ch
                          ? "border-violet-400 bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:border-violet-500/40 dark:text-violet-300"
                          : "border-slate-200 text-slate-600 dark:border-white/10 dark:text-slate-400 hover:border-violet-300"
                      }`}
                    >
                      {ch}
                    </button>
                  ))}
                </div>
              </div>

              {/* Subject (email only) */}
              {form.channel === "email" && (
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                    Subject
                  </label>
                  <input
                    value={form.subject}
                    onChange={(e) => setForm((p) => ({ ...p, subject: e.target.value }))}
                    placeholder="e.g. Welcome to {company_name}!"
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100"
                  />
                </div>
              )}

              {/* Body */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                  Body <span className="text-red-400">*</span>
                </label>
                <textarea
                  value={form.body}
                  onChange={(e) => setForm((p) => ({ ...p, body: e.target.value }))}
                  rows={8}
                  placeholder="Write your message here…"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100 resize-none font-mono"
                />
              </div>

              {/* Variable hints */}
              <div className="rounded-xl border border-dashed border-slate-200 dark:border-white/10 p-3 space-y-1.5">
                <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">Available variables</p>
                <div className="flex flex-wrap gap-1.5">
                  {VARIABLES.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setForm((p) => ({ ...p, body: p.body + v }))}
                      title={`Insert ${v}`}
                      className="rounded-lg bg-slate-100 dark:bg-slate-800 px-2 py-1 font-mono text-xs text-violet-700 dark:text-violet-300 hover:bg-violet-50 dark:hover:bg-violet-500/10 transition"
                    >
                      {v}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-400">Click a variable to insert it at end of body, or type it directly.</p>
              </div>

              {/* Preview section (only for existing saved templates) */}
              {!isNew && selectedId && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                    Preview with Lead
                  </p>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      value={previewLeadId}
                      onChange={(e) => setPreviewLeadId(e.target.value)}
                      placeholder="Lead ID"
                      min={1}
                      className="w-36 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100"
                    />
                    <button
                      onClick={handlePreview}
                      disabled={!previewLeadId || previewing}
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-50"
                    >
                      {previewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
                      Preview
                    </button>
                  </div>

                  {previewError && (
                    <div className="rounded-xl border border-red-200 bg-red-50 dark:bg-red-500/10 dark:border-red-500/20 px-4 py-3 text-sm text-red-600 dark:text-red-400">
                      {previewError}
                    </div>
                  )}

                  {preview && (
                    <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50/80 dark:bg-slate-800/40 p-4 space-y-3">
                      <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                        Rendered Preview
                      </p>
                      {preview.subject && (
                        <div>
                          <p className="text-xs text-slate-400 mb-0.5">Subject</p>
                          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{preview.subject}</p>
                        </div>
                      )}
                      <div>
                        <p className="text-xs text-slate-400 mb-0.5">Body</p>
                        <pre className="whitespace-pre-wrap font-sans text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                          {preview.body}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-3 pt-1 border-t border-slate-100 dark:border-white/5">
                <button
                  onClick={handleSave}
                  disabled={saving || !form.name.trim() || !form.body.trim()}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {isNew ? "Create Template" : "Save Changes"}
                </button>
                <button
                  onClick={cancelEdit}
                  className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
