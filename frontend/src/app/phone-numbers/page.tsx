"use client";

import { useState } from "react";
import { Bot, Phone, Plus, Search, Trash2, X, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type PhoneNumber = {
  id: number;
  provider: string;
  number: string;
  friendly_name?: string | null;
  capabilities: { voice?: boolean; sms?: boolean; mms?: boolean };
  status: string;
  assigned_agent_id?: number | null;
  monthly_cost?: string | null;
};

type AvailableNumber = {
  number: string;
  friendly_name: string;
  capabilities: { voice?: boolean; sms?: boolean; mms?: boolean };
  monthly_cost?: string | null;
  provider: string;
};

type VoiceAgent = { id: number; name: string };

const PROVIDERS = ["twilio", "plivo", "exotel", "vobiz"];
const COUNTRIES = [
  { code: "US", label: "United States" },
  { code: "IN", label: "India" },
  { code: "GB", label: "United Kingdom" },
  { code: "AU", label: "Australia" },
  { code: "CA", label: "Canada" },
  { code: "SG", label: "Singapore" },
];

export default function PhoneNumbersPage() {
  const { user } = useAuth();
  const [numbers, setNumbers] = useState<PhoneNumber[]>([]);
  const [agents, setAgents] = useState<VoiceAgent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Search modal state
  const [showSearch, setShowSearch] = useState(false);
  const [searchProvider, setSearchProvider] = useState("twilio");
  const [searchCountry, setSearchCountry] = useState("US");
  const [searchAreaCode, setSearchAreaCode] = useState("");
  const [searching, setSearching] = useState(false);
  const [available, setAvailable] = useState<AvailableNumber[]>([]);

  // Register modal (exotel/vobiz)
  const [showRegister, setShowRegister] = useState(false);
  const [registerProvider, setRegisterProvider] = useState("exotel");
  const [registerNumber, setRegisterNumber] = useState("");
  const [registerName, setRegisterName] = useState("");
  const [registering, setRegistering] = useState(false);

  const isRegisterOnly = (p: string) => p === "exotel" || p === "vobiz";

  async function request(url: string, init?: RequestInit) {
    const res = await apiFetch(url, init);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Error ${res.status}`);
    }
    return res;
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [numRes, agentRes] = await Promise.all([
        request(`${API_BASE}/crm/phone-numbers`),
        request(`${API_BASE}/crm/voice-agents`),
      ]);
      setNumbers(await numRes.json());
      const agentPayloads = await agentRes.json();
      setAgents(agentPayloads.map((p: { agent: VoiceAgent }) => p.agent));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  // Auto-load on mount
  useState(() => { if (user) void load(); });

  async function searchAvailable() {
    setSearching(true);
    setAvailable([]);
    try {
      const params = new URLSearchParams({ provider: searchProvider, country: searchCountry, limit: "20" });
      if (searchAreaCode) params.set("area_code", searchAreaCode);
      const res = await request(`${API_BASE}/crm/phone-numbers/search?${params}`);
      setAvailable(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function buyNumber(num: AvailableNumber) {
    try {
      await request(`${API_BASE}/crm/phone-numbers/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: num.provider, number: num.number, friendly_name: num.friendly_name }),
      });
      setMessage(`Purchased ${num.number}`);
      setShowSearch(false);
      setAvailable([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purchase failed");
    }
  }

  async function registerPhoneNumber() {
    setRegistering(true);
    try {
      await request(`${API_BASE}/crm/phone-numbers/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: registerProvider, number: registerNumber, friendly_name: registerName || registerNumber }),
      });
      setMessage(`Registered ${registerNumber}`);
      setShowRegister(false);
      setRegisterNumber("");
      setRegisterName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Register failed");
    } finally {
      setRegistering(false);
    }
  }

  async function releaseNumber(id: number, num: string) {
    if (!confirm(`Release ${num}? This cannot be undone.`)) return;
    try {
      await request(`${API_BASE}/crm/phone-numbers/${id}`, { method: "DELETE" });
      setMessage(`Released ${num}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Release failed");
    }
  }

  async function assignAgent(id: number, agentId: string) {
    try {
      await request(`${API_BASE}/crm/phone-numbers/${id}/assign`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId ? Number(agentId) : null }),
      });
      setMessage("Assignment updated");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assign failed");
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 p-6">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold flex items-center gap-2"><Phone className="h-6 w-6" /> Phone Numbers</h1>
            <p className="mt-1 text-sm text-slate-500">Manage telephony numbers across Twilio, Plivo, Exotel, and Vobiz</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowRegister(true)} className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
              <Plus className="h-4 w-4" /> Register DID
            </button>
            <button onClick={() => setShowSearch(true)} className="btn">
              <Search className="h-4 w-4" /> Search & Buy
            </button>
          </div>
        </div>

        {/* Alerts */}
        {error && (
          <div className="mb-4 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            <AlertCircle className="h-4 w-4 shrink-0" /> {error}
            <button onClick={() => setError(null)} className="ml-auto"><X className="h-4 w-4" /></button>
          </div>
        )}
        {message && (
          <div className="mb-4 flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
            <CheckCircle className="h-4 w-4 shrink-0" /> {message}
            <button onClick={() => setMessage(null)} className="ml-auto"><X className="h-4 w-4" /></button>
          </div>
        )}

        {/* Numbers table */}
        <div className="rounded-md border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          {loading ? (
            <div className="flex items-center justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
          ) : numbers.length === 0 ? (
            <div className="p-12 text-center text-slate-500">
              <Phone className="mx-auto mb-3 h-10 w-10 text-slate-300" />
              <p className="font-medium">No phone numbers yet</p>
              <p className="mt-1 text-sm">Search & buy a number or register an existing DID</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-800/50">
                <tr>
                  {["Number", "Provider", "Capabilities", "Assigned Agent", "Cost", "Actions"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {numbers.map((n) => (
                  <tr key={n.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-3 font-mono font-medium">{n.number}</td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs capitalize dark:bg-slate-800">{n.provider}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        {n.capabilities?.voice && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">Voice</span>}
                        {n.capabilities?.sms && <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-700 dark:bg-green-900/40 dark:text-green-300">SMS</span>}
                        {n.capabilities?.mms && <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">MMS</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        className="input py-1 text-sm"
                        value={n.assigned_agent_id ?? ""}
                        onChange={(e) => assignAgent(n.id, e.target.value)}
                      >
                        <option value="">Unassigned</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>{a.name}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{n.monthly_cost || "—"}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => releaseNumber(n.id, n.number)}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40"
                      >
                        <Trash2 className="h-3 w-3" /> Release
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Search & Buy Modal */}
      {showSearch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-2xl rounded-lg border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-700">
              <h2 className="text-lg font-semibold">Search Available Numbers</h2>
              <button onClick={() => { setShowSearch(false); setAvailable([]); }}><X className="h-5 w-5" /></button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Provider</span>
                  <select className="input" value={searchProvider} onChange={(e) => setSearchProvider(e.target.value)}>
                    {PROVIDERS.filter((p) => !isRegisterOnly(p)).map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Country</span>
                  <select className="input" value={searchCountry} onChange={(e) => setSearchCountry(e.target.value)}>
                    {COUNTRIES.map((c) => (
                      <option key={c.code} value={c.code}>{c.label}</option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Area Code (optional)</span>
                  <input className="input" placeholder="e.g. 415" value={searchAreaCode} onChange={(e) => setSearchAreaCode(e.target.value)} />
                </label>
              </div>
              <button onClick={searchAvailable} disabled={searching} className="btn">
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Search
              </button>

              {available.length > 0 && (
                <div className="mt-4 max-h-72 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-700">
                  {available.map((n) => (
                    <div key={n.number} className="flex items-center justify-between border-b border-slate-100 px-4 py-3 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/40">
                      <div>
                        <div className="font-mono font-medium">{n.number}</div>
                        <div className="text-xs text-slate-500">{n.friendly_name}{n.monthly_cost ? ` · $${n.monthly_cost}/mo` : ""}</div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex gap-1">
                          {n.capabilities?.voice && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">Voice</span>}
                          {n.capabilities?.sms && <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-700">SMS</span>}
                        </div>
                        <button onClick={() => buyNumber(n)} className="rounded-md bg-slate-950 px-3 py-1.5 text-xs text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100">
                          Buy
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Register DID Modal (Exotel / Vobiz) */}
      {showRegister && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-700">
              <h2 className="text-lg font-semibold">Register Existing DID</h2>
              <button onClick={() => setShowRegister(false)}><X className="h-5 w-5" /></button>
            </div>
            <div className="p-6 space-y-4">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Provider</span>
                <select className="input" value={registerProvider} onChange={(e) => setRegisterProvider(e.target.value)}>
                  {PROVIDERS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Phone Number (E.164)</span>
                <input className="input" placeholder="+919876543210" value={registerNumber} onChange={(e) => setRegisterNumber(e.target.value)} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Friendly Name (optional)</span>
                <input className="input" placeholder="Sales Line" value={registerName} onChange={(e) => setRegisterName(e.target.value)} />
              </label>
              <button onClick={registerPhoneNumber} disabled={registering || !registerNumber} className="btn w-full">
                {registering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Register Number
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
