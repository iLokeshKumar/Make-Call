"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Shield, ShieldCheck, UserCheck, UserX, Plus, X, Check, Edit2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type AdminUser = {
  id: number;
  email: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  is_active: boolean;
  email_verified: boolean;
  roles: string[];
  created_at?: string;
};

type AdminRole = {
  id: number;
  name: string;
  description?: string;
  is_system: boolean;
  permission_keys: string[];
};

type Permission = {
  id: number;
  key: string;
  description?: string;
};

type RoleFormState = {
  name: string;
  description: string;
  permission_keys: string[];
};

const emptyRoleForm: RoleFormState = { name: "", description: "", permission_keys: [] };

function Spinner() {
  return <Loader2 className="h-5 w-5 animate-spin text-violet-500" />;
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl dark:bg-slate-700">
      <Check className="h-4 w-4 text-emerald-400" />
      {message}
      <button onClick={onClose} className="ml-2 text-slate-400 hover:text-white">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function UsersTab({
  users, roles, sessionTimeout, onRefresh, onToast }: {
  users: AdminUser[];
  roles: AdminRole[];
  sessionTimeout: () => void;
  onRefresh: () => void;
  onToast: (msg: string) => void;
}) {
  const [assignRoleMap, setAssignRoleMap] = useState<Record<number, string>>({});
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});

  const authHeaders = {"Content-Type": "application/json" };

  const setLoading = (key: string, val: boolean) =>
    setLoadingMap((prev) => ({ ...prev, [key]: val }));

  const toggleStatus = async (user: AdminUser) => {
    const key = `status-${user.id}`;
    setLoading(key, true);
    try {
      const res = await apiFetch(`${API_BASE}/admin/users/${user.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !user.is_active }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) { onToast(`User ${user.is_active ? "deactivated" : "activated"} successfully`); onRefresh(); }
    } finally { setLoading(key, false); }
  };

  const assignRole = async (user: AdminUser) => {
    const roleId = Number(assignRoleMap[user.id]);
    if (!roleId) return;
    const key = `assign-${user.id}`;
    setLoading(key, true);
    try {
      const res = await apiFetch(`${API_BASE}/admin/users/${user.id}/roles`, {
        method: "POST",
        body: JSON.stringify({ role_id: roleId }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) {
        onToast("Role assigned");
        setAssignRoleMap((prev) => ({ ...prev, [user.id]: "" }));
        onRefresh();
      }
    } finally { setLoading(key, false); }
  };

  const removeRole = async (user: AdminUser, roleName: string) => {
    const role = roles.find((r) => r.name === roleName);
    if (!role) return;
    const key = `remove-${user.id}-${role.id}`;
    setLoading(key, true);
    try {
      const res = await apiFetch(`${API_BASE}/admin/users/${user.id}/roles/${role.id}`, {
        method: "DELETE" });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) { onToast("Role removed"); onRefresh(); }
    } finally { setLoading(key, false); }
  };

  const displayName = (u: AdminUser) => {
    const full = [u.first_name, u.last_name].filter(Boolean).join(" ");
    return full || u.username || u.email;
  };

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50/80 dark:bg-slate-800/50">
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Name / Email</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Roles</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Status</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Verified</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-slate-400">No users found</td>
            </tr>
          )}
          {users.map((user) => (
            <tr key={user.id} className="border-t border-slate-100 dark:border-white/5 hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
              <td className="px-4 py-3">
                <p className="font-medium text-slate-800 dark:text-slate-100">{displayName(user)}</p>
                <p className="text-xs text-slate-400">{user.email}</p>
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1.5">
                  {user.roles.length === 0 && (
                    <span className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 rounded-full px-2.5 py-1 text-xs font-medium">
                      No roles
                    </span>
                  )}
                  {user.roles.map((role) => (
                    <span key={role} className="group relative inline-flex items-center gap-1 bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300 rounded-full px-2.5 py-1 text-xs font-medium">
                      {role}
                      <button
                        onClick={() => removeRole(user, role)}
                        disabled={loadingMap[`remove-${user.id}-${roles.find((r) => r.name === role)?.id}`]}
                        className="ml-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:text-red-500"
                        title="Remove role"
                      >
                        {loadingMap[`remove-${user.id}-${roles.find((r) => r.name === role)?.id}`] ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <X className="h-3 w-3" />
                        )}
                      </button>
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-4 py-3">
                {user.is_active ? (
                  <span className="bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300 rounded-full px-2.5 py-1 text-xs font-medium">
                    Active
                  </span>
                ) : (
                  <span className="bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300 rounded-full px-2.5 py-1 text-xs font-medium">
                    Inactive
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                {user.email_verified ? (
                  <span className="bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300 rounded-full px-2.5 py-1 text-xs font-medium">
                    Verified
                  </span>
                ) : (
                  <span className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 rounded-full px-2.5 py-1 text-xs font-medium">
                    Unverified
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => toggleStatus(user)}
                    disabled={loadingMap[`status-${user.id}`]}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 disabled:opacity-50 transition"
                  >
                    {loadingMap[`status-${user.id}`] ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : user.is_active ? (
                      <UserX className="h-3 w-3 text-red-500" />
                    ) : (
                      <UserCheck className="h-3 w-3 text-emerald-500" />
                    )}
                    {user.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <div className="flex items-center gap-1">
                    <select
                      value={assignRoleMap[user.id] ?? ""}
                      onChange={(e) =>
                        setAssignRoleMap((prev) => ({ ...prev, [user.id]: e.target.value }))
                      }
                      className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-300"
                    >
                      <option value="">Assign role…</option>
                      {roles.map((r) => (
                        <option key={r.id} value={r.id}>{r.name}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => assignRole(user)}
                      disabled={!assignRoleMap[user.id] || loadingMap[`assign-${user.id}`]}
                      className="inline-flex items-center gap-1 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-40 transition"
                    >
                      {loadingMap[`assign-${user.id}`] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                      Assign
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* Roles Tab */
function RolesTab({
  roles, permissions, sessionTimeout, onRefresh, onToast }: {
  roles: AdminRole[];
  permissions: Permission[];
  sessionTimeout: () => void;
  onRefresh: () => void;
  onToast: (msg: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [editingRole, setEditingRole] = useState<AdminRole | null>(null);
  const [form, setForm] = useState<RoleFormState>(emptyRoleForm);
  const [saving, setSaving] = useState(false);

  const authHeaders = {"Content-Type": "application/json" };

  const openNew = () => {
    setEditingRole(null);
    setForm(emptyRoleForm);
    setShowForm(true);
  };

  const openEdit = (role: AdminRole) => {
    setEditingRole(role);
    setForm({ name: role.name, description: role.description ?? "", permission_keys: [...role.permission_keys] });
    setShowForm(true);
  };

  const cancelForm = () => {
    setShowForm(false);
    setEditingRole(null);
    setForm(emptyRoleForm);
  };

  const togglePermission = (key: string) => {
    setForm((prev) => ({
      ...prev,
      permission_keys: prev.permission_keys.includes(key)
        ? prev.permission_keys.filter((k) => k !== key)
        : [...prev.permission_keys, key] }));
  };

  const saveRole = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        permission_keys: form.permission_keys };
      const res = editingRole
        ? await apiFetch(`${API_BASE}/admin/roles/${editingRole.id}`, {
            method: "PUT",
            body: JSON.stringify(body) })
        : await apiFetch(`${API_BASE}/admin/roles`, {
            method: "POST",
            body: JSON.stringify(body) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) {
        onToast(editingRole ? "Role updated" : "Role created");
        cancelForm();
        onRefresh();
      }
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={openNew} className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20">
          <Plus className="h-4 w-4" /> New Role
        </button>
      </div>

      <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50/80 dark:bg-slate-800/50">
              <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Name</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Description</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">System</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Permissions</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Actions</th>
            </tr>
          </thead>
          <tbody>
            {roles.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-400">No roles found</td>
              </tr>
            )}
            {roles.map((role) => (
              <tr key={role.id} className="border-t border-slate-100 dark:border-white/5 hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-100">{role.name}</td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{role.description ?? "—"}</td>
                <td className="px-4 py-3">
                  {role.is_system ? (
                    <span className="bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300 rounded-full px-2.5 py-1 text-xs font-medium inline-flex items-center gap-1">
                      <ShieldCheck className="h-3 w-3" /> System
                    </span>
                  ) : (
                    <span className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 rounded-full px-2.5 py-1 text-xs font-medium">
                      Custom
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {role.permission_keys.slice(0, 3).map((pk) => (
                      <span key={pk} className="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 rounded-full px-2 py-0.5 text-xs font-medium">
                        {pk}
                      </span>
                    ))}
                    {role.permission_keys.length > 3 && (
                      <span className="bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300 rounded-full px-2 py-0.5 text-xs font-medium">
                        +{role.permission_keys.length - 3} more
                      </span>
                    )}
                    {role.permission_keys.length === 0 && (
                      <span className="text-xs text-slate-400">None</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  {!role.is_system && (
                    <button
                      onClick={() => openEdit(role)}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition"
                    >
                      <Edit2 className="h-3 w-3" /> Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showForm && (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-5">
          <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            {editingRole ? "Edit Role" : "New Role"}
          </h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                Role Name <span className="text-red-400">*</span>
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="e.g. Sales Manager"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
                Description
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                rows={2}
                placeholder="Describe this role's purpose…"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-100 resize-none"
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600 dark:text-slate-400 uppercase tracking-wide">
              Permissions
            </label>
            {permissions.length === 0 && (
              <p className="text-xs text-slate-400">No permissions available</p>
            )}
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-64 overflow-y-auto pr-1">
              {permissions.map((perm) => {
                const checked = form.permission_keys.includes(perm.key);
                return (
                  <label
                    key={perm.key}
                    className={`flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition ${
                      checked
                        ? "border-violet-400 bg-violet-50 dark:bg-violet-500/10 dark:border-violet-500/40"
                        : "border-slate-200 dark:border-white/10 hover:border-violet-300 dark:hover:border-violet-500/30"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => togglePermission(perm.key)}
                      className="mt-0.5 h-3.5 w-3.5 accent-violet-600"
                    />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-slate-700 dark:text-slate-200">{perm.key}</p>
                      {perm.description && (
                        <p className="truncate text-xs text-slate-400">{perm.description}</p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="flex gap-3 pt-1">
            <button
              onClick={saveRole}
              disabled={saving || !form.name.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {editingRole ? "Update Role" : "Create Role"}
            </button>
            <button
              onClick={cancelForm}
              className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PermissionsTab({ permissions }: { permissions: Permission[] }) {
  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50/80 dark:bg-slate-800/50">
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Key</th>
            <th className="px-4 py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Description</th>
          </tr>
        </thead>
        <tbody>
          {permissions.length === 0 && (
            <tr>
              <td colSpan={2} className="px-4 py-8 text-center text-slate-400">No permissions defined</td>
            </tr>
          )}
          {permissions.map((perm) => (
            <tr key={perm.key} className="border-t border-slate-100 dark:border-white/5 hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
              <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                {perm.key}
              </td>
              <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{perm.description ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* TabPFN training-seed uploader */
function TabPFNSeedCard({ sessionTimeout, onToast }: {
  sessionTimeout: () => void;
  onToast: (msg: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgError, setMsgError] = useState(false);

  const upload = async () => {
    if (!file) return;
    setUploading(true); setMsg(null); setMsgError(false);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await apiFetch(`${API_BASE}/proposals/tabpfn/seed`, { method: "POST", body: fd });
      if (res.status === 401) { sessionTimeout(); return; }
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = body?.detail;
        throw new Error(typeof detail === "string" ? detail : "Upload failed.");
      }
      setMsg(`Ingested ${body?.ingested ?? 0} training rows.`);
      onToast("TabPFN training data seeded");
      setFile(null);
    } catch (e) {
      setMsgError(true);
      setMsg(e instanceof Error ? e.message : "Upload failed.");
    } finally { setUploading(false); }
  };

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">Training Seed</h3>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Upload an Excel sheet of past deals to seed the proposal win-score model. The sheet needs a
          win/loss column (<code>target</code> / <code>outcome</code> / <code>win</code>) plus any feature
          columns (<code>deal_size</code>, <code>discount_percent</code>, <code>industry</code>…). Applies company-wide.
        </p>
      </div>
      {msg && (
        <div className={`rounded-xl px-4 py-2 text-sm ${
          msgError
            ? "bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/20"
            : "bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20"
        }`}>
          {msg}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".xlsx,.xls"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm text-slate-600 dark:text-slate-300 file:mr-3 file:rounded-xl file:border-0 file:bg-violet-100 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-violet-700 dark:file:bg-violet-500/10 dark:file:text-violet-300"
        />
        <button
          onClick={upload}
          disabled={!file || uploading}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-50"
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Upload &amp; Seed
        </button>
      </div>
    </div>
  );
}

/* Page */
export default function AdminPage() {
  const { user, sessionTimeout } = useAuth();
  const [activeTab, setActiveTab] = useState<"Users" | "Roles" | "Permissions">("Users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);


  const fetchAll = useCallback(async () => {
    if (!user) { setLoading(false); return; }
    setLoading(true);
    try {
      const [uRes, rRes, pRes] = await Promise.all([
        apiFetch(`${API_BASE}/admin/users`),
        apiFetch(`${API_BASE}/admin/roles`),
        apiFetch(`${API_BASE}/admin/permissions`),
      ]);
      if (uRes.status === 401 || rRes.status === 401 || pRes.status === 401) {
        sessionTimeout();
        return;
      }
      if (uRes.ok) setUsers(await uRes.json());
      if (rRes.ok) setRoles(await rRes.json());
      if (pRes.ok) setPermissions(await pRes.json());
    } finally { setLoading(false); }
  }, [user]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const TABS = ["Users", "Roles", "Permissions"] as const;

  return (
    <div className="space-y-6 pb-8">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}

      {/* Header */}
      <div>
        <h1 className="text-4xl font-bold tracking-tight">
          <span className="gradient-text">Admin Panel</span>
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
          Manage users, roles and permissions
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 rounded-xl bg-slate-100/80 dark:bg-slate-800/50 p-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition ${
              activeTab === tab
                ? "bg-white shadow dark:bg-slate-700 text-slate-900 dark:text-white"
                : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner />
        </div>
      ) : (
        <>
          {activeTab === "Users" && (
            <UsersTab
              users={users}
              roles={roles}
              sessionTimeout={sessionTimeout}
              onRefresh={fetchAll}
              onToast={setToast}
            />
          )}
          {activeTab === "Roles" && (
            <RolesTab
              roles={roles}
              permissions={permissions}
              sessionTimeout={sessionTimeout}
              onRefresh={fetchAll}
              onToast={setToast}
            />
          )}
          {activeTab === "Permissions" && <PermissionsTab permissions={permissions} />}
        </>
      )}

      <TabPFNSeedCard sessionTimeout={sessionTimeout} onToast={setToast} />
    </div>
  );
}
