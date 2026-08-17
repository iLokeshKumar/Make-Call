"use client";

import React, { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import UserChip from "@/components/UserChip";
import {
  Loader2,
  Pencil,
  Plus,
  Search,
  Star,
  ToggleLeft,
  ToggleRight,
  User,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type Contact = {
  id: number;
  account_id?: number;
  lead_id?: number;
  owner_user_id?: number;
  name: string;
  email?: string;
  phone?: string;
  designation?: string;
  department?: string;
  is_primary: boolean;
  preferred_language?: string;
  notes?: string;
  is_active: boolean;
  created_at?: string;
};

type Account = { id: number; name: string };
type Lead = { id: number; name: string };

type ContactForm = {
  name: string;
  email: string;
  phone: string;
  designation: string;
  department: string;
  account_id: string;
  lead_id: string;
  is_primary: boolean;
  preferred_language: string;
  notes: string;
};

const LANGUAGES = [
  { value: "", label: "None" },
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "ta", label: "Tamil" },
  { value: "te", label: "Telugu" },
  { value: "kn", label: "Kannada" },
  { value: "mr", label: "Marathi" },
  { value: "gu", label: "Gujarati" },
];

const emptyForm: ContactForm = {
  name: "",
  email: "",
  phone: "",
  designation: "",
  department: "",
  account_id: "",
  lead_id: "",
  is_primary: false,
  preferred_language: "",
  notes: "",
};

function contactToForm(c: Contact): ContactForm {
  return {
    name: c.name,
    email: c.email ?? "",
    phone: c.phone ?? "",
    designation: c.designation ?? "",
    department: c.department ?? "",
    account_id: c.account_id != null ? String(c.account_id) : "",
    lead_id: c.lead_id != null ? String(c.lead_id) : "",
    is_primary: c.is_primary,
    preferred_language: c.preferred_language ?? "",
    notes: c.notes ?? "",
  };
}

function formToPayload(f: ContactForm): Record<string, unknown> {
  return {
    name: f.name.trim(),
    ...(f.email.trim() && { email: f.email.trim() }),
    ...(f.phone.trim() && { phone: f.phone.trim() }),
    ...(f.designation.trim() && { designation: f.designation.trim() }),
    ...(f.department.trim() && { department: f.department.trim() }),
    ...(f.account_id && { account_id: Number(f.account_id) }),
    ...(f.lead_id && { lead_id: Number(f.lead_id) }),
    is_primary: f.is_primary,
    ...(f.preferred_language && { preferred_language: f.preferred_language }),
    ...(f.notes.trim() && { notes: f.notes.trim() }),
  };
}

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white";
const labelClass = "block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1";

export default function ContactsPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  const [search, setSearch] = useState("");

  // Panel state
  const [panelOpen, setPanelOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<ContactForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Lead search inside form
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);

  // Toggle loading
  const [togglingId, setTogglingId] = useState<number | null>(null);

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  // Queries
  const contactsQuery = useQuery<Contact[]>({
    queryKey: ["contacts"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/contacts`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load contacts");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const accountsQuery = useQuery<Account[]>({
    queryKey: ["contacts-accounts"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/accounts`);
      if (!res.ok) return [];
      const d = await res.json();
      return Array.isArray(d) ? d : d.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["contacts-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const contacts: Contact[] = contactsQuery.data ?? [];
  const accounts: Account[] = accountsQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = contactsQuery.isLoading;

  const accountMap = Object.fromEntries(accounts.map((a) => [a.id, a.name]));

  const fetchContacts = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["contacts"] });
  }, [qc]);

  // Filtered leads for lead selector in form
  const filteredLeadsForForm = leads.filter((l) =>
    l.name.toLowerCase().includes(leadSearch.toLowerCase())
  );

  // Filtered contacts
  const filtered = contacts.filter((c) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      c.name.toLowerCase().includes(q) ||
      (c.email ?? "").toLowerCase().includes(q) ||
      (c.designation ?? "").toLowerCase().includes(q)
    );
  });

  // Stats
  const primaryCount = contacts.filter((c) => c.is_primary).length;
  const activeCount = contacts.filter((c) => c.is_active).length;

  function openCreate() {
    setForm(emptyForm);
    setEditId(null);
    setSaveError(null);
    setLeadSearch("");
    setSelectedLeadId(null);
    setPanelOpen(true);
  }

  function openEdit(contact: Contact) {
    setForm(contactToForm(contact));
    setEditId(contact.id);
    setSaveError(null);
    const lead = leads.find((l) => l.id === contact.lead_id);
    setLeadSearch(lead ? lead.name : "");
    setSelectedLeadId(contact.lead_id ?? null);
    setPanelOpen(true);
  }

  function closePanel() {
    setPanelOpen(false);
    setEditId(null);
    setSaveError(null);
    setLeadSearch("");
    setSelectedLeadId(null);
  }

  function handleFormChange(field: keyof ContactForm, value: string | boolean) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    if (!form.name.trim()) { setSaveError("Name is required"); return; }
    setSaving(true);
    setSaveError(null);
    try {
      const payload = formToPayload(form);
      const url = editId
        ? `${API_BASE}/crm/contacts/${editId}`
        : `${API_BASE}/crm/contacts`;
      const method = editId ? "PATCH" : "POST";
      const res = await apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `Server ${res.status}`);
      }
      showToast(editId ? "Contact updated" : "Contact created");
      closePanel();
      fetchContacts();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleActive(contact: Contact) {
    setTogglingId(contact.id);
    try {
      const res = await apiFetch(`${API_BASE}/crm/contacts/${contact.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !contact.is_active }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to update contact");
      showToast(contact.is_active ? "Contact deactivated" : "Contact activated");
      fetchContacts();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Update failed", true);
    } finally {
      setTogglingId(null);
    }
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            CRM
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Contacts</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Manage people associated with accounts and leads
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
          >
            <Plus className="h-4 w-4" /> New Contact
          </button>
          <UserChip />
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm transition-all ${
            toastError
              ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
              : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
          }`}
        >
          {toast}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Contacts", value: contacts.length, icon: Users, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Primary Contacts", value: primaryCount, icon: Star, color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-100 dark:bg-amber-500/10" },
          { label: "Active", value: activeCount, icon: User, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex items-center gap-4">
            <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${bg}`}>
              <Icon className={`h-5 w-5 ${color}`} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          placeholder="Search by name, email, designation…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading contacts…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {!search
            ? "No contacts yet. Create your first contact above."
            : `No contacts match "${search}".`}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Name", "Email", "Phone", "Designation", "Department", "Account", "Primary", "Language", "Active", "Actions"].map((col) => (
                    <th key={col} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {filtered.map((contact) => (
                  <tr key={contact.id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors">
                    {/* Name */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-blue-500 text-white text-xs font-bold">
                          {contact.name.charAt(0).toUpperCase()}
                        </div>
                        <span className="font-medium text-slate-800 dark:text-slate-100 whitespace-nowrap">
                          {contact.name}
                        </span>
                      </div>
                    </td>
                    {/* Email */}
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {contact.email ? (
                        <a href={`mailto:${contact.email}`} className="hover:text-violet-600 dark:hover:text-violet-300 hover:underline">
                          {contact.email}
                        </a>
                      ) : "—"}
                    </td>
                    {/* Phone */}
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {contact.phone ?? "—"}
                    </td>
                    {/* Designation */}
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {contact.designation ?? "—"}
                    </td>
                    {/* Department */}
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {contact.department ?? "—"}
                    </td>
                    {/* Account */}
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {contact.account_id ? (accountMap[contact.account_id] ?? `#${contact.account_id}`) : "—"}
                    </td>
                    {/* Primary badge */}
                    <td className="px-4 py-3">
                      {contact.is_primary ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                          <Star className="h-3 w-3 fill-amber-500 text-amber-500" />
                          Primary
                        </span>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    {/* Language */}
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {LANGUAGES.find((l) => l.value === contact.preferred_language)?.label ?? "—"}
                    </td>
                    {/* Active toggle */}
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleToggleActive(contact)}
                        disabled={togglingId === contact.id}
                        title={contact.is_active ? "Deactivate" : "Activate"}
                        className="flex items-center gap-1.5 disabled:opacity-50"
                      >
                        {togglingId === contact.id ? (
                          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
                        ) : contact.is_active ? (
                          <ToggleRight className="h-6 w-6 text-emerald-500" />
                        ) : (
                          <ToggleLeft className="h-6 w-6 text-slate-400" />
                        )}
                        <span className={`text-xs font-medium ${contact.is_active ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}`}>
                          {contact.is_active ? "Active" : "Inactive"}
                        </span>
                      </button>
                    </td>
                    {/* Actions */}
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEdit(contact)}
                        title="Edit contact"
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-violet-600 dark:hover:bg-white/10 dark:hover:text-violet-300"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Right slide-in panel */}
      {panelOpen && (
        <div className="fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="flex-1 bg-black/40 backdrop-blur-sm"
            onClick={closePanel}
          />
          {/* Panel */}
          <div className="w-full max-w-lg bg-white dark:bg-slate-900 shadow-2xl overflow-y-auto flex flex-col">
            {/* Panel header */}
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 px-6 py-4 sticky top-0 bg-white dark:bg-slate-900 z-10">
              <h2 className="text-base font-semibold text-slate-900 dark:text-white">
                {editId ? "Edit Contact" : "New Contact"}
              </h2>
              <button
                onClick={closePanel}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 px-6 py-5 space-y-4">
              {saveError && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400">
                  {saveError}
                </div>
              )}

              {/* Name */}
              <div>
                <label className={labelClass}>Name <span className="text-red-500">*</span></label>
                <input
                  value={form.name}
                  onChange={(e) => handleFormChange("name", e.target.value)}
                  placeholder="Full name"
                  className={inputClass}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {/* Email */}
                <div>
                  <label className={labelClass}>Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => handleFormChange("email", e.target.value)}
                    placeholder="name@company.com"
                    className={inputClass}
                  />
                </div>

                {/* Phone */}
                <div>
                  <label className={labelClass}>Phone</label>
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={(e) => handleFormChange("phone", e.target.value)}
                    placeholder="+91 99999 99999"
                    className={inputClass}
                  />
                </div>

                {/* Designation */}
                <div>
                  <label className={labelClass}>Designation</label>
                  <input
                    value={form.designation}
                    onChange={(e) => handleFormChange("designation", e.target.value)}
                    placeholder="e.g. Sales Manager"
                    className={inputClass}
                  />
                </div>

                {/* Department */}
                <div>
                  <label className={labelClass}>Department</label>
                  <input
                    value={form.department}
                    onChange={(e) => handleFormChange("department", e.target.value)}
                    placeholder="e.g. Operations"
                    className={inputClass}
                  />
                </div>

                {/* Account */}
                <div>
                  <label className={labelClass}>Account</label>
                  <select
                    value={form.account_id}
                    onChange={(e) => handleFormChange("account_id", e.target.value)}
                    className={inputClass}
                  >
                    <option value="">No account</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>

                {/* Language */}
                <div>
                  <label className={labelClass}>Preferred Language</label>
                  <select
                    value={form.preferred_language}
                    onChange={(e) => handleFormChange("preferred_language", e.target.value)}
                    className={inputClass}
                  >
                    {LANGUAGES.map((l) => (
                      <option key={l.value} value={l.value}>{l.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Lead selector */}
              <div className="relative">
                <label className={labelClass}>Lead (optional)</label>
                <input
                  value={leadSearch}
                  onChange={(e) => {
                    setLeadSearch(e.target.value);
                    setSelectedLeadId(null);
                    handleFormChange("lead_id", "");
                  }}
                  placeholder="Search lead name…"
                  className={inputClass}
                />
                {leadSearch && !selectedLeadId && filteredLeadsForForm.length > 0 && (
                  <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900 max-h-40 overflow-y-auto">
                    {filteredLeadsForForm.slice(0, 10).map((l) => (
                      <button
                        key={l.id}
                        onClick={() => {
                          setSelectedLeadId(l.id);
                          setLeadSearch(l.name);
                          handleFormChange("lead_id", String(l.id));
                        }}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-violet-50 dark:hover:bg-violet-500/10 text-slate-800 dark:text-slate-100"
                      >
                        {l.name}
                      </button>
                    ))}
                  </div>
                )}
                {selectedLeadId && (
                  <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">Lead selected (ID {selectedLeadId})</p>
                )}
              </div>

              {/* Notes */}
              <div>
                <label className={labelClass}>Notes</label>
                <textarea
                  value={form.notes}
                  onChange={(e) => handleFormChange("notes", e.target.value)}
                  rows={3}
                  placeholder="Optional notes about this contact…"
                  className={`${inputClass} resize-none`}
                />
              </div>

              {/* Is Primary */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_primary"
                  checked={form.is_primary}
                  onChange={(e) => handleFormChange("is_primary", e.target.checked)}
                  className="h-4 w-4 rounded accent-amber-500"
                />
                <label
                  htmlFor="is_primary"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200 cursor-pointer flex items-center gap-1.5"
                >
                  <Star className="h-3.5 w-3.5 text-amber-500" />
                  Primary contact
                </label>
              </div>
            </div>

            {/* Panel footer */}
            <div className="border-t border-slate-200 dark:border-white/10 px-6 py-4 flex gap-3 sticky bottom-0 bg-white dark:bg-slate-900">
              <button
                onClick={handleSave}
                disabled={saving || !form.name.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {editId ? "Save Changes" : "Create Contact"}
              </button>
              <button
                onClick={closePanel}
                className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
