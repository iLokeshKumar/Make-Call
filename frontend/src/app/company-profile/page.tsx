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

  contact_email?: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  country?: string;
  pincode?: string;
  gst_number?: string;
  pan_number?: string;
  nature_of_business?: string;
  vat_number?: string;
  cin_number?: string;

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
            <div className="space-y-2 text-sm font-semibold">
              <span>Company Logo</span>
              <div className="flex items-center gap-3 mt-1">
                {form.logo_url ? (
                  <img
                    src={form.logo_url}
                    alt="Company logo"
                    className="h-14 w-14 rounded-xl object-contain border border-slate-200 bg-slate-50 p-1"
                  />
                ) : (
                  <div className="h-14 w-14 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 flex items-center justify-center text-slate-400 text-xs">
                    No logo
                  </div>
                )}
                <div className="flex-1 space-y-1">
                  <label className="cursor-pointer inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      disabled={logoUploading}
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        setLogoUploading(true);
                        setLogoFeedback(null);
                        try {
                          const fd = new FormData();
                          fd.append("file", file);
                          const res = await fetch(`${API_BASE}/company-profile/logo`, {
                            method: "POST",
                            headers: { Authorization: `Bearer ${token}` },
                            body: fd,
                          });
                          if (!res.ok) throw new Error("Upload failed");
                          const data = await res.json();
                          setForm({ ...form, logo_url: data.logo_url });
                          setLogoFeedback("Logo updated");
                        } catch {
                          setLogoFeedback("Upload failed");
                        } finally {
                          setLogoUploading(false);
                          e.target.value = "";
                        }
                      }}
                    />
                    {logoUploading ? "Uploading…" : "Upload logo"}
                  </label>
                  {logoFeedback && (
                    <p className={`text-xs ${logoFeedback === "Logo updated" ? "text-emerald-500" : "text-red-500"}`}>
                      {logoFeedback}
                    </p>
                  )}
                  {form.logo_url && (
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, logo_url: "" })}
                      className="text-xs text-red-400 hover:text-red-600"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            </div>
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

          {/* ── Contact & Billing (used on quotes/PDFs) ── */}
          <div className="pt-2 border-t border-slate-100">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Contact &amp; Billing — shown on quotes &amp; invoices</p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm font-semibold">
                <span>Contact Email</span>
                <input type="email" value={form.contact_email ?? ""}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                  placeholder="billing@yourcompany.com"
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>Phone</span>
                <input type="tel" value={form.phone ?? ""}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  placeholder="+91 98765 43210"
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
            </div>
            <div className="mt-4">
              <label className="space-y-2 text-sm font-semibold">
                <span>Street Address</span>
                <input type="text" value={form.address ?? ""}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="Building, Street, Area"
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-4 mt-4 md:grid-cols-4">
              <label className="space-y-2 text-sm font-semibold">
                <span>City</span>
                <input type="text" value={form.city ?? ""}
                  onChange={(e) => setForm({ ...form, city: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>State</span>
                <input type="text" value={form.state ?? ""}
                  onChange={(e) => setForm({ ...form, state: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>Pincode</span>
                <input type="text" value={form.pincode ?? ""}
                  onChange={(e) => setForm({ ...form, pincode: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>Country</span>
                <input type="text" value={form.country ?? ""}
                  onChange={(e) => setForm({ ...form, country: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
            </div>
            <div className="grid grid-cols-1 gap-4 mt-4 md:grid-cols-2">
              <label className="space-y-2 text-sm font-semibold">
                <span>GST Number</span>
                <input type="text" value={form.gst_number ?? ""}
                  onChange={(e) => setForm({ ...form, gst_number: e.target.value })}
                  placeholder="22AAAAA0000A1Z5"
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>PAN Number</span>
                <input type="text" value={form.pan_number ?? ""}
                  onChange={(e) => setForm({ ...form, pan_number: e.target.value })}
                  placeholder="AAAAA0000A"
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>Nature of Business</span>
                <input type="text" value={form.nature_of_business ?? ""}
                  onChange={(e) => setForm({ ...form, nature_of_business: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>VAT Number</span>
                <input type="text" value={form.vat_number ?? ""}
                  onChange={(e) => setForm({ ...form, vat_number: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>
              <label className="space-y-2 text-sm font-semibold">
                <span>CIN Number</span>
                <input type="text" value={form.cin_number ?? ""}
                  onChange={(e) => setForm({ ...form, cin_number: e.target.value })}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </label>

            </div>
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

