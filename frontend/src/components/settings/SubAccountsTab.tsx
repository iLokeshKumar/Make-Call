"use client";

import { useEffect, useState, useCallback } from "react";
import { Layers, Plus, Trash2, Shield, Eye, Loader2, Play, AlertCircle, RefreshCw } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE, CRM_BASE } from "@/lib/api";

type SubAccount = {
  id: number;
  name: string;
  slug: string;
  status: string;
  max_concurrent_calls: number;
  daily_call_cap: number | null;
  max_users: number;
  subscription_tier: string;
  routing_region: string;
  created_at: string | null;
};

type UsageSummary = {
  id: number;
  name: string;
  status: string;
  max_concurrent_calls: number;
  daily_call_cap: number | null;
  usage: Record<string, number>;
};

type AggregatedUsage = {
  month: string;
  sub_accounts: UsageSummary[];
  totals: Record<string, number>;
};

export default function SubAccountsTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [subs, setSubs] = useState<SubAccount[]>([]);
  const [usage, setUsage] = useState<AggregatedUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [concurrencyStatus, setConcurrencyStatus] = useState<Record<number, string>>({});
  const [checkingConcurrency, setCheckingConcurrency] = useState<number | null>(null);

  // Form State
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    slug: "",
    subscription_tier: "starter",
    max_users: 3,
    max_concurrent_calls: 2,
    daily_call_cap: "",
    routing_region: "global",
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [subsRes, usageRes] = await Promise.all([
        apiFetch(`${CRM_BASE}/sub-accounts`),
        apiFetch(`${CRM_BASE}/sub-accounts/usage/aggregated`),
      ]);
      if (subsRes.status === 401 || usageRes.status === 401) {
        sessionTimeout();
        return;
      }
      if (subsRes.ok) setSubs(await subsRes.json());
      if (usageRes.ok) setUsage(await usageRes.json());
    } catch (e) {
      console.error("Failed to load sub-accounts", e);
    } finally {
      setLoading(false);
    }
  }, [sessionTimeout]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.slug.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        ...form,
        daily_call_cap: form.daily_call_cap ? Number(form.daily_call_cap) : null,
      };
      const res = await apiFetch(`${CRM_BASE}/sub-accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to create sub-account");
      }
      setShowModal(false);
      setForm({
        name: "",
        slug: "",
        subscription_tier: "starter",
        max_users: 3,
        max_concurrent_calls: 2,
        daily_call_cap: "",
        routing_region: "global",
      });
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Creation failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("Are you sure you want to disable this sub-account?")) return;
    setDeletingId(id);
    try {
      const res = await apiFetch(`${CRM_BASE}/sub-accounts/${id}`, {
        method: "DELETE",
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        fetchData();
      }
    } finally {
      setDeletingId(null);
    }
  };

  const checkConcurrency = async (id: number) => {
    setCheckingConcurrency(id);
    try {
      const res = await apiFetch(`${CRM_BASE}/sub-accounts/${id}/concurrency-check`);
      if (res.ok) {
        const data = await res.json();
        setConcurrencyStatus((prev) => ({
          ...prev,
          [id]: data.allowed ? "Within limits (OK)" : `Exceeded: ${data.reason}`,
        }));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setCheckingConcurrency(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-violet-500" />
        Loading sub-accounts data...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Overview stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Sub Accounts</span>
          <span className="text-3xl font-bold text-slate-800 dark:text-white mt-2">{subs.length}</span>
          <span className="text-xs text-slate-400 mt-1">Managed organizations</span>
        </div>
        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Active month calls</span>
          <span className="text-3xl font-bold text-slate-800 dark:text-white mt-2">
            {usage?.totals?.calls || 0}
          </span>
          <span className="text-xs text-slate-400 mt-1">Aggregated call volume</span>
        </div>
        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Sub-account emails</span>
          <span className="text-3xl font-bold text-slate-800 dark:text-white mt-2">
            {usage?.totals?.emails || 0}
          </span>
          <span className="text-xs text-slate-400 mt-1">Aggregated email volume</span>
        </div>
      </div>

      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-purple-600">
              <Layers className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Sub Accounts</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Partitioned client companies managed under your main tenant</p>
            </div>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors"
          >
            <Plus className="h-4 w-4" /> Create Sub Account
          </button>
        </div>

        {subs.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-8">No sub-accounts registered. Click &ldquo;Create Sub Account&rdquo; to add one.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-3 text-left">Company Name</th>
                  <th className="px-4 py-3 text-left">Tier / Region</th>
                  <th className="px-4 py-3 text-left">Concurrency Limit</th>
                  <th className="px-4 py-3 text-left">Daily Call Cap</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {subs.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                    <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                      <div>{s.name}</div>
                      <div className="text-xs text-slate-400 font-mono">@{s.slug}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                      <span className="capitalize">{s.subscription_tier}</span>
                      <span className="text-slate-400 mx-1.5">·</span>
                      <span className="uppercase text-xs">{s.routing_region}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300 font-mono">
                      {s.max_concurrent_calls} calls max
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300 font-mono">
                      {s.daily_call_cap || "Unlimited"}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${s.status === "active" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300" : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"}`}>
                        {s.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => checkConcurrency(s.id)}
                          disabled={checkingConcurrency === s.id}
                          className="px-2 py-1 text-xs font-semibold rounded border border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 inline-flex items-center gap-1.5"
                          title="Check live concurrency status"
                        >
                          {checkingConcurrency === s.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                          Check limit
                        </button>
                        {concurrencyStatus[s.id] && (
                          <span className="text-xs text-violet-600 font-medium font-mono">{concurrencyStatus[s.id]}</span>
                        )}
                        <button
                          onClick={() => handleDelete(s.id)}
                          disabled={deletingId === s.id}
                          className="p-1.5 text-slate-400 hover:text-red-600 transition-colors ml-auto"
                        >
                          {deletingId === s.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal Form */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
              <h2 className="font-bold text-slate-900 dark:text-slate-100">Create Sub Account</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              {error && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 flex items-center gap-2"><AlertCircle className="h-4 w-4" />{error}</div>}
              
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Account Name</label>
                  <input
                    required
                    value={form.name}
                    onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                    placeholder="Talentrus Distribution Ltd."
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Slug</label>
                  <input
                    required
                    value={form.slug}
                    onChange={e => setForm(p => ({ ...p, slug: e.target.value.replace(/[^a-zA-Z0-9-]/g, "").toLowerCase() }))}
                    placeholder="talentrus-dist"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Subscription Tier</label>
                  <select
                    value={form.subscription_tier}
                    onChange={e => setForm(p => ({ ...p, subscription_tier: e.target.value }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  >
                    <option value="starter">Starter</option>
                    <option value="growth">Growth</option>
                    <option value="professional">Professional</option>
                    <option value="enterprise">Enterprise</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Max Concurrent Calls</label>
                  <input
                    type="number"
                    value={form.max_concurrent_calls}
                    onChange={e => setForm(p => ({ ...p, max_concurrent_calls: Number(e.target.value) }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Daily Call Cap (optional)</label>
                  <input
                    type="number"
                    value={form.daily_call_cap}
                    onChange={e => setForm(p => ({ ...p, daily_call_cap: e.target.value }))}
                    placeholder="e.g. 500"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Max Users</label>
                  <input
                    type="number"
                    value={form.max_users}
                    onChange={e => setForm(p => ({ ...p, max_users: Number(e.target.value) }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Routing Region</label>
                  <select
                    value={form.routing_region}
                    onChange={e => setForm(p => ({ ...p, routing_region: e.target.value }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  >
                    <option value="global">Global (US)</option>
                    <option value="india">India (Mumbai)</option>
                    <option value="europe">Europe (Frankfurt)</option>
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-850">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !form.name.trim() || !form.slug.trim()}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create Account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
