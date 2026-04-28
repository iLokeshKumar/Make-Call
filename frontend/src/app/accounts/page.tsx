"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  ExternalLink,
  Globe,
  Loader2,
  MapPin,
  Pencil,
  Plus,
  Search,
  Trash2,
  Users } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// Types

type Account = {
  id: number;
  name: string;
  industry?: string | null;
  website?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  employee_count?: number | null;
  notes?: string | null;
  is_active: boolean;
  created_at?: string;
};

type AccountForm = {
  name: string;
  industry: string;
  website: string;
  city: string;
  state: string;
  country: string;
  employee_count: string;
  notes: string;
  is_active: boolean;
};

const emptyForm: AccountForm = {
  name: "",
  industry: "",
  website: "",
  city: "",
  state: "",
  country: "",
  employee_count: "",
  notes: "",
  is_active: true };

// Helpers

function formToPayload(f: AccountForm): Record<string, unknown> {
  return {
    name: f.name.trim(),
    ...(f.industry.trim() && { industry: f.industry.trim() }),
    ...(f.website.trim() && { website: f.website.trim() }),
    ...(f.city.trim() && { city: f.city.trim() }),
    ...(f.state.trim() && { state: f.state.trim() }),
    ...(f.country.trim() && { country: f.country.trim() }),
    ...(f.employee_count && { employee_count: Number(f.employee_count) }),
    ...(f.notes.trim() && { notes: f.notes.trim() }),
    is_active: f.is_active };
}

function accountToForm(a: Account): AccountForm {
  return {
    name: a.name,
    industry: a.industry ?? "",
    website: a.website ?? "",
    city: a.city ?? "",
    state: a.state ?? "",
    country: a.country ?? "",
    employee_count: a.employee_count != null ? String(a.employee_count) : "",
    notes: a.notes ?? "",
    is_active: a.is_active };
}

function locationString(a: Account): string {
  return [a.city, a.state, a.country].filter(Boolean).join(", ") || "";
}

// Account Card

function AccountCard({
  account, onEdit, onDelete, deleting }: {
  account: Account;
  onEdit: (a: Account) => void;
  onDelete: (id: number) => void;
  deleting: boolean;
}) {
  const loc = locationString(account);

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex flex-col gap-3 hover:shadow-lg hover:shadow-violet-500/5 transition-shadow">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 text-white">
            <Building2 className="h-4 w-4" />
          </div>
          <h3 className="font-semibold text-slate-800 dark:text-white text-base leading-tight truncate">
            {account.name}
          </h3>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
            account.is_active
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
              : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
          }`}
        >
          {account.is_active ? "Active" : "Inactive"}
        </span>
      </div>

      {/* Industry */}
      {account.industry && (
        <span className="inline-flex w-fit items-center rounded-lg bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
          {account.industry}
        </span>
      )}

      {/* Website */}
      {account.website && (
        <a
          href={
            account.website.startsWith("http")
              ? account.website
              : `https://${account.website}`
          }
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-sm text-blue-600 dark:text-blue-400 hover:underline w-fit max-w-full"
        >
          <Globe className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{account.website}</span>
          <ExternalLink className="h-3 w-3 shrink-0" />
        </a>
      )}

      {/* Location */}
      {loc && (
        <div className="flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400">
          <MapPin className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{loc}</span>
        </div>
      )}

      {/* Employee count */}
      {account.employee_count != null && (
        <div className="flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400">
          <Users className="h-3.5 w-3.5 shrink-0" />
          <span>{account.employee_count.toLocaleString()} employees</span>
        </div>
      )}

      {/* Notes */}
      {account.notes && (
        <p className="text-xs text-slate-400 dark:text-slate-500 leading-relaxed">
          {account.notes.length > 80
            ? account.notes.slice(0, 80) + "…"
            : account.notes}
        </p>
      )}

      {/* Action buttons */}
      <div className="mt-auto flex items-center gap-2 pt-2 border-t border-slate-100 dark:border-white/5">
        <button
          onClick={() => onEdit(account)}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5 transition-colors"
        >
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </button>
        <button
          onClick={() => onDelete(account.id)}
          disabled={deleting}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {deleting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Trash2 className="h-3.5 w-3.5" />
          )}
          Delete
        </button>
      </div>
    </div>
  );
}

// Form Panel

function AccountFormPanel({
  form, saving, editId, onChange, onSave, onCancel, error }: {
  form: AccountForm;
  saving: boolean;
  editId: number | null;
  onChange: (field: keyof AccountForm, value: string | boolean) => void;
  onSave: () => void;
  onCancel: () => void;
  error: string | null;
}) {
  const inputClass =
    "rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white w-full";
  const labelClass = "block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1";

  return (
    <div className="rounded-2xl glass border border-violet-200 dark:border-violet-500/20 p-6 shadow-lg shadow-violet-500/5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-base font-semibold text-slate-800 dark:text-white">
          {editId ? "Edit Account" : "New Account"}
        </h2>
        <button
          onClick={onCancel}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
        >
          Cancel
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Name */}
        <div className="sm:col-span-2 lg:col-span-1">
          <label className={labelClass}>
            Name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            className={inputClass}
            placeholder="Acme Corporation"
            value={form.name}
            onChange={(e) => onChange("name", e.target.value)}
          />
        </div>

        {/* Industry */}
        <div>
          <label className={labelClass}>Industry</label>
          <input
            type="text"
            className={inputClass}
            placeholder="Technology"
            value={form.industry}
            onChange={(e) => onChange("industry", e.target.value)}
          />
        </div>

        {/* Website */}
        <div>
          <label className={labelClass}>Website</label>
          <input
            type="text"
            className={inputClass}
            placeholder="acme.com"
            value={form.website}
            onChange={(e) => onChange("website", e.target.value)}
          />
        </div>

        {/* City */}
        <div>
          <label className={labelClass}>City</label>
          <input
            type="text"
            className={inputClass}
            placeholder="San Francisco"
            value={form.city}
            onChange={(e) => onChange("city", e.target.value)}
          />
        </div>

        {/* State */}
        <div>
          <label className={labelClass}>State</label>
          <input
            type="text"
            className={inputClass}
            placeholder="CA"
            value={form.state}
            onChange={(e) => onChange("state", e.target.value)}
          />
        </div>

        {/* Country */}
        <div>
          <label className={labelClass}>Country</label>
          <input
            type="text"
            className={inputClass}
            placeholder="USA"
            value={form.country}
            onChange={(e) => onChange("country", e.target.value)}
          />
        </div>

        {/* Employee count */}
        <div>
          <label className={labelClass}>Employee Count</label>
          <input
            type="number"
            min={0}
            className={inputClass}
            placeholder="250"
            value={form.employee_count}
            onChange={(e) => onChange("employee_count", e.target.value)}
          />
        </div>

        {/* Notes */}
        <div className="sm:col-span-2">
          <label className={labelClass}>Notes</label>
          <textarea
            rows={3}
            className={`${inputClass} resize-none`}
            placeholder="Optional notes about this account…"
            value={form.notes}
            onChange={(e) => onChange("notes", e.target.value)}
          />
        </div>

        {/* Active */}
        <div className="flex items-center gap-2 pt-5">
          <input
            type="checkbox"
            id="is_active"
            checked={form.is_active}
            onChange={(e) => onChange("is_active", e.target.checked)}
            className="h-4 w-4 rounded accent-violet-600"
          />
          <label
            htmlFor="is_active"
            className="text-sm font-medium text-slate-600 dark:text-slate-300 cursor-pointer"
          >
            Active account
          </label>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving || !form.name.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {editId ? "Save Changes" : "Create Account"}
        </button>
        <button
          onClick={onCancel}
          className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// Main Page

export default function AccountsPage() {
  const { user, sessionTimeout } = useAuth();

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<AccountForm>(emptyForm);
  const [editId, setEditId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Fetch accounts

  const fetchAccounts = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/accounts`, {
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.status === 404 || res.status === 405) {
        setApiUnavailable(true);
        setLoading(false);
        return;
      }
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setAccounts(Array.isArray(data) ? data : data.items ?? []);
      setFetchError(null);
      setApiUnavailable(false);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Failed to load accounts");
    } finally {
      setLoading(false);
    }
  }, [user, sessionTimeout]);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  // Form helpers

  function openCreate() {
    setForm(emptyForm);
    setEditId(null);
    setSaveError(null);
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openEdit(account: Account) {
    setForm(accountToForm(account));
    setEditId(account.id);
    setSaveError(null);
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleFormChange(field: keyof AccountForm, value: string | boolean) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleCancel() {
    setShowForm(false);
    setEditId(null);
    setSaveError(null);
  }

  // Save

  async function handleSave() {
    if (!user || !form.name.trim()) return;
    setSaving(true);
    setSaveError(null);
    const payload = formToPayload(form);
    try {
      const url = editId
        ? `${API_BASE}/crm/accounts/${editId}`
        : `${API_BASE}/crm/accounts`;
      const method = editId ? "PATCH" : "POST";
      const res = await apiFetch(url, {
        method,
        headers: {
          "Content-Type": "application/json" },
        body: JSON.stringify(payload) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `Server ${res.status}`
        );
      }
      setShowForm(false);
      setEditId(null);
      await fetchAccounts();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Delete

  async function handleDelete(id: number) {
    if (!user) return;
    if (!window.confirm("Delete this account? This action cannot be undone.")) return;
    setDeletingId(id);
    try {
      const res = await apiFetch(`${API_BASE}/crm/accounts/${id}`, {
        method: "DELETE"
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Server ${res.status}`);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  // Filtered accounts

  const filtered = accounts.filter((a) =>
    a.name.toLowerCase().includes(query.toLowerCase())
  );

  // Render

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-8">

        {/* Header */}
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800 dark:text-white">
              <Building2 className="h-6 w-6 text-violet-500" />
              Accounts
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Manage organizations and link leads to accounts.
            </p>
          </div>
          {!apiUnavailable && (
            <button
              onClick={openCreate}
              className="mt-3 sm:mt-0 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20"
            >
              <Plus className="h-4 w-4" />
              New Account
            </button>
          )}
        </div>

        {/* API unavailable notice */}
        {apiUnavailable && (
          <div className="rounded-2xl glass border border-amber-200 dark:border-amber-500/20 p-8 text-center">
            <Building2 className="mx-auto mb-3 h-10 w-10 text-amber-400 opacity-60" />
            <h3 className="text-base font-semibold text-slate-700 dark:text-slate-200">
              Accounts are not yet configured in the backend.
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              The <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">/crm/accounts</code> endpoint returned 404. Please enable accounts in your backend configuration.
            </p>
          </div>
        )}

        {/* Fetch error */}
        {fetchError && !apiUnavailable && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400">
            {fetchError}
          </div>
        )}

        {/* Form panel */}
        {showForm && !apiUnavailable && (
          <AccountFormPanel
            form={form}
            saving={saving}
            editId={editId}
            onChange={handleFormChange}
            onSave={handleSave}
            onCancel={handleCancel}
            error={saveError}
          />
        )}

        {/* Search bar */}
        {!apiUnavailable && !loading && (
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search accounts…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
            />
          </div>
        )}

        {/* Loading spinner */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
          </div>
        )}

        {/* Empty state */}
        {!loading && !apiUnavailable && !fetchError && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-600">
            <Building2 className="h-12 w-12 mb-3 opacity-30" />
            <p className="text-sm font-medium">
              {query
                ? `No accounts match "${query}"`
                : "No accounts yet. Create your first one."}
            </p>
            {!query && (
              <button
                onClick={openCreate}
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20"
              >
                <Plus className="h-4 w-4" />
                New Account
              </button>
            )}
          </div>
        )}

        {/* Account cards grid */}
        {!loading && !apiUnavailable && filtered.length > 0 && (
          <>
            <p className="text-xs text-slate-400 dark:text-slate-600">
              {filtered.length} account{filtered.length !== 1 ? "s" : ""}
              {query && ` matching "${query}"`}
            </p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {filtered.map((account) => (
                <AccountCard
                  key={account.id}
                  account={account}
                  onEdit={openEdit}
                  onDelete={handleDelete}
                  deleting={deletingId === account.id}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
