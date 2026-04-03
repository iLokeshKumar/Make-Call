"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Building2, Globe, Link, Palette, Sliders, Users, ShieldCheck } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type CompanyProfile = {
  name: string;
  slug: string;
  domain?: string;
  website?: string;
  logo_url?: string;
  primary_color?: string;
  status: string;
  subscription_tier: string;
  max_users: number;
};

const STATUS_OPTIONS = ["Active", "Suspended", "Trial"];
const TIER_OPTIONS = ["Starter", "Growth", "Professional", "Enterprise"];

export default function CompanyProfilePage() {
  const { user, token, isLoading, sessionTimeout } = useAuth();
  const router = useRouter();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [form, setForm] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logoUploading, setLogoUploading] = useState(false);
  const [logoFeedback, setLogoFeedback] = useState<string | null>(null);

  const isAdmin = !!user && ["company_owner", "company_admin"].includes(user.role);

  const fetchProfile = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/company-profile`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        throw new Error("Unable to load company profile.");
      }
      const data: CompanyProfile = await res.json();
      setProfile(data);
      setForm(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load company profile.");
    } finally {
      setLoading(false);
    }
  }, [token, sessionTimeout]);

  useEffect(() => {
    if (!isLoading && !isAdmin) {
      router.push("/");
      return;
    }
    if (isAdmin) {
      fetchProfile();
    }
  }, [isAdmin, isLoading, router, fetchProfile]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token || !form) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/company-profile`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(form),
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.detail || "Update failed.");
      }
      const data = await res.json();
      setProfile(data);
      setMessage("Company profile updated.");
    } catch (err) {
      setMessage(null);
      setError(err instanceof Error ? err.message : "Update failed.");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return null;
  }

  return (
    <div className="space-y-6 pb-8">
      <div>
        <h1 className="text-4xl font-bold tracking-tight">
          <span className="gradient-text">Company Profile</span>
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
          Manage the name, branding, and operational settings for your tenant.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12 text-slate-500">
          <ShieldCheck className="mr-2 h-5 w-5 animate-spin" />
          Loading company profile…
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {error}
        </div>
      ) : form ? (
        <form onSubmit={handleSubmit} className="glass-panel p-8 rounded-3xl space-y-6 border border-white/20">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm font-semibold">
              <span>Name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Slug</span>
              <input
                type="text"
                required
                value={form.slug}
                onChange={(e) => setForm({ ...form, slug: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Domain</span>
              <input
                type="text"
                value={form.domain ?? ""}
                onChange={(e) => setForm({ ...form, domain: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Website</span>
              <input
                type="url"
                value={form.website ?? ""}
                onChange={(e) => setForm({ ...form, website: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm font-semibold">
              <span>Logo URL</span>
              <input
                type="url"
                value={form.logo_url ?? ""}
                onChange={(e) => setForm({ ...form, logo_url: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Primary color</span>
              <input
                type="text"
                placeholder="#7c3aed"
                value={form.primary_color ?? ""}
                onChange={(e) => setForm({ ...form, primary_color: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <label className="space-y-2 text-sm font-semibold">
              <span>Status</span>
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Subscription tier</span>
              <select
                value={form.subscription_tier}
                onChange={(e) => setForm({ ...form, subscription_tier: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              >
                {TIER_OPTIONS.map((tier) => (
                  <option key={tier} value={tier}>
                    {tier}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm font-semibold">
              <span>Max users</span>
              <input
                type="number"
                min={1}
                value={form.max_users}
                onChange={(e) =>
                  setForm({
                    ...form,
                    max_users: Number(e.target.value) || 0,
                  })
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </label>
          </div>

          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/40 transition-all hover:shadow-xl disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save changes"}
            </button>
            {message && <span className="text-sm text-emerald-400">{message}</span>}
          </div>
        </form>
      ) : null}
    </div>
  );
}

