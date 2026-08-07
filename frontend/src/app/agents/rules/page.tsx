"use client";

/**
 * Rules admin — CRUD for the data-driven rules engine.
 *
 * Layout: header + "new rule" button, then a priority-ordered table.
 * Each row: toggle active, inline edit of name/priority, full edit via modal.
 * Modal has three fields: name, priority, when_json (raw JSON textarea with
 * schema help), then_action (verb dropdown + conditional argument input).
 *
 * Backend validates the DSL on every write, so we don't duplicate that here
 * — just a smooth error flow if the server rejects malformed input.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle, AlertTriangle, CheckCircle, ChevronDown, ChevronUp,
  Loader2, Pencil, Plus, Power, RefreshCw, Trash2, X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import UserChip from "@/components/UserChip";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";



// Types

type IsmRule = {
  id: number;
  company_id: number;
  name: string;
  description: string | null;
  priority: number;
  when_json: Record<string, unknown>;
  then_action: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

type RuleFormData = {
  name: string;
  description: string;
  priority: number;
  when_json_text: string;   // JSON as string while editing
  then_action_verb: "advance_to" | "dispatch" | "handoff_to_human" | "skip";
  then_action_arg: string;
  is_active: boolean;
};

// Constants matching the backend DSL validator

const ACTION_VERBS = [
  { value: "advance_to" as const, label: "Advance stage", hasArg: true,
    argChoices: ["new", "contacted", "engaged", "quote_sent", "negotiation", "closed_won", "closed_lost"] },
  { value: "dispatch" as const, label: "Dispatch channel", hasArg: true,
    argChoices: ["call", "whatsapp", "email", "send_email", "send_whatsapp", "send_quote"] },
  { value: "handoff_to_human" as const, label: "Handoff to human", hasArg: false, argChoices: [] as string[] },
  { value: "skip" as const, label: "Skip (no-op)", hasArg: false, argChoices: [] as string[] },
];

// Helpers

function parseThenAction(action: string): { verb: RuleFormData["then_action_verb"]; arg: string } {
  const [verb, ...rest] = action.split(":");
  const v = (verb?.trim() ?? "skip") as RuleFormData["then_action_verb"];
  return { verb: v, arg: rest.join(":").trim() };
}

function composeThenAction(verb: RuleFormData["then_action_verb"], arg: string): string {
  if (verb === "handoff_to_human" || verb === "skip") return verb;
  return `${verb}:${arg}`;
}

function emptyForm(): RuleFormData {
  return {
    name: "",
    description: "",
    priority: 10,
    when_json_text: "{}",
    then_action_verb: "skip",
    then_action_arg: "",
    is_active: true,
  };
}

// Rule row

function RuleRow({ rule, onEdit, onToggle, onDelete, busy }: {
  rule: IsmRule;
  onEdit: (r: IsmRule) => void;
  onToggle: (r: IsmRule) => void;
  onDelete: (r: IsmRule) => void;
  busy: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const isBusy = busy === rule.id;

  return (
    <>
      <tr className={`border-b border-white/5 ${rule.is_active ? "" : "opacity-50"}`}>
        <td className="px-3 py-2 text-sm text-slate-300 font-mono">{rule.priority}</td>
        <td className="px-3 py-2">
          <div className="text-sm text-slate-200 font-medium">{rule.name}</div>
          {rule.description && (
            <div className="text-xs text-slate-500 mt-0.5">{rule.description}</div>
          )}
        </td>
        <td className="px-3 py-2 text-xs text-slate-400 font-mono max-w-[280px] truncate">
          {Object.keys(rule.when_json).length === 0
            ? <span className="text-slate-600 italic">any</span>
            : JSON.stringify(rule.when_json)}
        </td>
        <td className="px-3 py-2 text-sm">
          <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/25 text-xs font-mono">
            {rule.then_action}
          </span>
        </td>
        <td className="px-3 py-2">
          <button
            onClick={() => onToggle(rule)}
            disabled={isBusy}
            className={`p-1.5 rounded transition-colors ${
              rule.is_active
                ? "bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25"
                : "bg-slate-500/15 text-slate-500 hover:bg-slate-500/25"
            }`}
            title={rule.is_active ? "Click to disable" : "Click to enable"}
          >
            <Power className="w-3.5 h-3.5" />
          </button>
        </td>
        <td className="px-3 py-2 text-right whitespace-nowrap">
          <button
            onClick={() => setExpanded(e => !e)}
            className="p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
            title="Expand"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          <button
            onClick={() => onEdit(rule)}
            className="p-1.5 text-slate-500 hover:text-indigo-400 transition-colors"
            title="Edit"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            onClick={() => onDelete(rule)}
            disabled={isBusy}
            className="p-1.5 text-slate-500 hover:text-red-400 transition-colors"
            title="Delete"
          >
            {isBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-white/5 bg-black/20">
          <td colSpan={6} className="px-3 py-3">
            <div className="text-xs text-slate-500 mb-1 uppercase tracking-wide">Full when_json</div>
            <pre className="text-xs text-slate-300 bg-black/40 rounded p-2 overflow-x-auto">
              {JSON.stringify(rule.when_json, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

// Rule edit modal

function RuleModal({ initial, onClose, onSaved }: {
  initial: IsmRule | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<RuleFormData>(() => {
    if (!initial) return emptyForm();
    const parsed = parseThenAction(initial.then_action);
    return {
      name: initial.name,
      description: initial.description ?? "",
      priority: initial.priority,
      when_json_text: JSON.stringify(initial.when_json, null, 2),
      then_action_verb: parsed.verb,
      then_action_arg: parsed.arg,
      is_active: initial.is_active,
    };
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeVerb = ACTION_VERBS.find(v => v.value === form.then_action_verb);

  const save = async () => {
    setError(null);

    // Client-side: validate JSON parses
    let when_json: Record<string, unknown>;
    try {
      when_json = JSON.parse(form.when_json_text);
      if (typeof when_json !== "object" || Array.isArray(when_json)) {
        throw new Error("when_json must be a JSON object");
      }
    } catch (e) {
      setError(`Invalid when_json: ${(e as Error).message}`);
      return;
    }

    const then_action = composeThenAction(form.then_action_verb, form.then_action_arg);
    if (activeVerb?.hasArg && !form.then_action_arg) {
      setError(`"${form.then_action_verb}" requires an argument.`);
      return;
    }

    setSaving(true);
    try {
      const isUpdate = initial !== null;
      const url = isUpdate
        ? `${API_BASE}/crm/ism-rules/${initial.id}`
        : `${API_BASE}/crm/ism-rules`;
      const res = await apiFetch(url, {
        method: isUpdate ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          description: form.description || null,
          priority: form.priority,
          when_json,
          then_action,
          is_active: form.is_active,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Server ${res.status}`);
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-slate-900 border border-white/10 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10">
          <h2 className="text-slate-100 font-semibold">
            {initial ? `Edit rule: ${initial.name}` : "New ISM rule"}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {error && (
            <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-400">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Name + priority */}
          <div className="grid grid-cols-4 gap-3">
            <div className="col-span-3">
              <label className="text-xs text-slate-500 mb-1 block">Name</label>
              <input
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="e.g. vip_handoff"
                className="w-full bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Priority</label>
              <input
                type="number"
                value={form.priority}
                onChange={e => setForm(f => ({ ...f, priority: Number(e.target.value) }))}
                className="w-full bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
              />
              <p className="text-xs text-slate-600 mt-1">Lower = higher</p>
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Description <span className="text-slate-600">(optional)</span></label>
            <input
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="Why does this rule exist?"
              className="w-full bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* when_json */}
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Conditions (when_json)</label>
            <textarea
              value={form.when_json_text}
              onChange={e => setForm(f => ({ ...f, when_json_text: e.target.value }))}
              rows={6}
              spellCheck={false}
              className="w-full bg-black/40 border border-white/10 rounded px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            />
            <details className="mt-1">
              <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400">
                Operators reference
              </summary>
              <div className="text-xs text-slate-500 mt-1 font-mono space-y-0.5 pl-3">
                <div>stage: "engaged"  |  stages: ["engaged", "quote_sent"]</div>
                <div>has_email: true  |  has_phone: true</div>
                <div>lead_score_min: 50  |  lead_score_max: 80</div>
                <div>days_since_contact_min: 7  |  days_since_contact_max: 30</div>
                <div>budget_usd_min: 10000  |  budget_usd_max: 100000</div>
                <div>urgency: "urgent" | "routine"</div>
              </div>
            </details>
          </div>

          {/* then_action */}
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Action</label>
            <div className="flex gap-2">
              <select
                value={form.then_action_verb}
                onChange={e => setForm(f => ({
                  ...f,
                  then_action_verb: e.target.value as RuleFormData["then_action_verb"],
                  then_action_arg: "",
                }))}
                className="bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                {ACTION_VERBS.map(v => (
                  <option key={v.value} value={v.value}>{v.label}</option>
                ))}
              </select>
              {activeVerb?.hasArg && (
                <select
                  value={form.then_action_arg}
                  onChange={e => setForm(f => ({ ...f, then_action_arg: e.target.value }))}
                  className="flex-1 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="">— select —</option>
                  {activeVerb.argChoices.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              )}
            </div>
          </div>

          {/* is_active */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
              className="w-4 h-4 accent-emerald-500"
            />
            <span className="text-sm text-slate-300">Active</span>
          </label>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-white/10">
          <button onClick={onClose}
                  className="px-3 py-1.5 rounded text-sm text-slate-400 hover:text-slate-200 transition-colors">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving || !form.name.trim()}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded text-sm bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/30 disabled:opacity-40 transition-colors"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
            {initial ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Main page

export default function IsmRulesPage() {
  const { user, sessionTimeout } = useAuth();
  const [rules, setRules] = useState<IsmRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalRule, setModalRule] = useState<IsmRule | null | "new">(null);  // null = closed, "new" = create
  const [busy, setBusy] = useState<number | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const fetchRules = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/ism-rules`);
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Server ${res.status}`);
      setRules(await res.json());
      setFetchError(null);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, [user, sessionTimeout]);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const toggleRule = async (rule: IsmRule) => {
    setBusy(rule.id);
    try {
      await apiFetch(`${API_BASE}/crm/ism-rules/${rule.id}/toggle`, { method: "POST" });
      await fetchRules();
    } finally { setBusy(null); }
  };

  const deleteRule = async (rule: IsmRule) => {
    if (!window.confirm(`Delete rule "${rule.name}"? This cannot be undone.`)) return;
    setBusy(rule.id);
    try {
      await apiFetch(`${API_BASE}/crm/ism-rules/${rule.id}`, { method: "DELETE" });
      await fetchRules();
    } finally { setBusy(null); }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <AlertTriangle className="w-6 h-6 text-amber-400" />
            ISM Rules
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Data-driven overrides for stage-based ISM behavior. Lower priority runs first.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <UserChip />
          <button onClick={fetchRules} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm text-slate-300 border border-white/10 hover:bg-white/5">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button onClick={() => setModalRule("new")} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/30">
            <Plus className="w-4 h-4" /> New rule
          </button>
        </div>
      </div>

      {fetchError && (
        <div className="mb-4 rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-400">
          {fetchError}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
      ) : rules.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <AlertTriangle className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No rules yet. <button onClick={() => setModalRule("new")} className="text-indigo-400 underline">Create one</button> to override stage-default behavior.</p>
        </div>
      ) : (
        <div className="border border-white/10 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-black/30 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Prio</th>
                <th className="px-3 py-2 text-left font-medium">Name</th>
                <th className="px-3 py-2 text-left font-medium">When</th>
                <th className="px-3 py-2 text-left font-medium">Then</th>
                <th className="px-3 py-2 text-left font-medium">Active</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rules.map(rule => (
                <RuleRow key={rule.id} rule={rule}
                         onEdit={r => setModalRule(r)}
                         onToggle={toggleRule}
                         onDelete={deleteRule}
                         busy={busy} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalRule !== null && (
        <RuleModal
          initial={modalRule === "new" ? null : modalRule}
          onClose={() => setModalRule(null)}
          onSaved={fetchRules}
        />
      )}
    </div>
  );
}
