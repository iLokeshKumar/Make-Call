"use client";

import { useEffect, useState, useCallback } from "react";
import { Gauge, Calendar, User, DollarSign, Clock, Phone, Loader2, ArrowUpDown } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");
const CRM_BASE = `${API_BASE}/crm`;

type VoiceAgent = {
  id: number;
  name: string;
};

type CostRow = {
  date: string;
  currency: string;
  total_calls: number;
  total_minutes: number;
  stt_cost: number;
  llm_cost: number;
  tts_cost: number;
  telephony_cost: number;
  total_cost: number;
  cost_per_minute: number;
};

export default function CostTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [breakdown, setBreakdown] = useState<CostRow[]>([]);
  const [agents, setAgents] = useState<VoiceAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [liveRate, setLiveRate] = useState<number | null>(null);

  // Filters
  const [currency, setCurrency] = useState("USD");
  const [selectedAgentId, setSelectedAgentId] = useState<string>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Provider Rates Config
  type ConfiguredRate = {
    id: number;
    category: string;
    provider: string;
    model_or_voice: string | null;
    rate_per_second: number;
    is_active: boolean;
  };
  const [ratesList, setRatesList] = useState<ConfiguredRate[]>([]);
  const [ratesLoading, setRatesLoading] = useState(false);
  const [formCategory, setFormCategory] = useState("stt");
  const [formProvider, setFormProvider] = useState("");
  const [formModelVoice, setFormModelVoice] = useState("");
  const [formRatePerSecond, setFormRatePerSecond] = useState("");
  const [submittingRate, setSubmittingRate] = useState(false);


  const fetchFiltersAndRate = useCallback(async () => {
    try {
      const agentsRes = await apiFetch(`${CRM_BASE}/voice-agents`);
      if (agentsRes.ok) {
        const data = await agentsRes.json();
        setAgents(Array.isArray(data) ? data.map(item => item.agent || item) : []);
      }

      if (currency !== "USD") {
        const rateRes = await apiFetch(`${CRM_BASE}/cost/live-rate?from_currency=USD&to_currency=${currency}`);
        if (rateRes.ok) {
          const rateData = await rateRes.json();
          setLiveRate(rateData.rate);
        }
      } else {
        setLiveRate(null);
      }
    } catch (e) {
      console.error(e);
    }
  }, [currency]);

  const fetchBreakdown = useCallback(async () => {
    setLoading(true);
    try {
      let url = `${CRM_BASE}/cost/breakdown?currency=${currency}`;
      if (selectedAgentId !== "all") url += `&agent_id=${selectedAgentId}`;
      if (startDate) url += `&start_date=${startDate}`;
      if (endDate) url += `&end_date=${endDate}`;

      const res = await apiFetch(url);
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setBreakdown(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [currency, selectedAgentId, startDate, endDate, sessionTimeout]);

  useEffect(() => {
    fetchFiltersAndRate();
  }, [fetchFiltersAndRate]);

  useEffect(() => {
    fetchBreakdown();
  }, [fetchBreakdown]);

  const fetchRates = useCallback(async () => {
    setRatesLoading(true);
    try {
      const res = await apiFetch(`${CRM_BASE}/cost/rates`);
      if (res.ok) {
        setRatesList(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setRatesLoading(false);
    }
  }, []);

  const handleAddRate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formProvider) return;
    const rateVal = parseFloat(formRatePerSecond);
    if (isNaN(rateVal) || rateVal < 0) return;

    setSubmittingRate(true);
    try {
      const res = await apiFetch(`${CRM_BASE}/cost/rates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: formCategory,
          provider: formProvider,
          model_or_voice: formModelVoice || null,
          rate_per_second: rateVal,
          is_active: true,
        }),
      });
      if (res.ok) {
        setFormProvider("");
        setFormModelVoice("");
        setFormRatePerSecond("");
        fetchRates();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSubmittingRate(false);
    }
  };

  const handleDeleteRate = async (id: number) => {
    try {
      const res = await apiFetch(`${CRM_BASE}/cost/rates/${id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        fetchRates();
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchRates();
  }, [fetchRates]);


  // Aggregate stats from breakdown rows
  const stats = breakdown.reduce((acc, row) => {
    acc.totalCalls += row.total_calls;
    acc.totalMinutes += row.total_minutes;
    acc.totalCost += row.total_cost;
    acc.sttCost += row.stt_cost;
    acc.llmCost += row.llm_cost;
    acc.ttsCost += row.tts_cost;
    acc.telephonyCost += row.telephony_cost;
    return acc;
  }, {
    totalCalls: 0,
    totalMinutes: 0,
    totalCost: 0,
    sttCost: 0,
    llmCost: 0,
    ttsCost: 0,
    telephonyCost: 0,
  });

  const avgCostPerMinute = stats.totalMinutes > 0 ? stats.totalCost / stats.totalMinutes : 0;

  const currencySymbols: Record<string, string> = {
    USD: "$",
    EUR: "€",
    GBP: "£",
    INR: "₹",
    AUD: "A$",
    CAD: "C$",
    SGD: "S$",
    JPY: "¥",
    AED: "د.إ",
    CNY: "¥",
  };

  const fmtCost = (val: number) => {
    const symbol = currencySymbols[currency] || `${currency} `;
    return `${symbol}${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  };

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-wrap items-center gap-4 justify-between">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Target Currency</span>
            <select
              value={currency}
              onChange={e => setCurrency(e.target.value)}
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            >
              <option value="USD">USD ($)</option>
              <option value="INR">INR (₹)</option>
              <option value="EUR">EUR (€)</option>
              <option value="GBP">GBP (£)</option>
              <option value="AUD">AUD (A$)</option>
              <option value="CAD">CAD (C$)</option>
              <option value="SGD">SGD (S$)</option>
              <option value="JPY">JPY (¥)</option>
              <option value="AED">AED (د.إ)</option>
              <option value="CNY">CNY (¥)</option>
            </select>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Voice Agent</span>
            <select
              value={selectedAgentId}
              onChange={e => setSelectedAgentId(e.target.value)}
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            >
              <option value="all">All Agents</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Start Date</span>
            <input
              type="date"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              className="p-1.5 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            />
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">End Date</span>
            <input
              type="date"
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              className="p-1.5 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            />
          </div>
        </div>

        {liveRate && (
          <div className="bg-violet-50/50 dark:bg-violet-950/20 px-3 py-2 rounded-xl border border-violet-100 dark:border-violet-900/40 text-xs text-violet-700 dark:text-violet-300 font-semibold font-mono">
            Forex conversion rate: 1 USD = {liveRate.toFixed(2)} INR
          </div>
        )}
      </div>

      {/* Aggregate Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Est. Cost</span>
            <DollarSign className="h-4 w-4 text-emerald-500" />
          </div>
          <span className="text-2xl font-bold text-slate-800 dark:text-white mt-2">{fmtCost(stats.totalCost)}</span>
          <span className="text-[10px] text-slate-400 mt-1">Aggregated across all calls</span>
        </div>

        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Calls</span>
            <Phone className="h-4 w-4 text-blue-500" />
          </div>
          <span className="text-2xl font-bold text-slate-800 dark:text-white mt-2">{stats.totalCalls}</span>
          <span className="text-[10px] text-slate-400 mt-1">Successfully recorded logs</span>
        </div>

        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Duration</span>
            <Clock className="h-4 w-4 text-violet-500" />
          </div>
          <span className="text-2xl font-bold text-slate-800 dark:text-white mt-2">{stats.totalMinutes.toFixed(1)} mins</span>
          <span className="text-[10px] text-slate-400 mt-1">Talk time active pipeline</span>
        </div>

        <div className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Avg Cost / min</span>
            <ArrowUpDown className="h-4 w-4 text-yellow-500" />
          </div>
          <span className="text-2xl font-bold text-slate-800 dark:text-white mt-2">{fmtCost(avgCostPerMinute)}</span>
          <span className="text-[10px] text-slate-400 mt-1">Provider cost optimization rate</span>
        </div>
      </div>

      {/* Sub-services breakdown cost details */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-4">
        <h4 className="font-bold text-sm text-slate-800 dark:text-slate-200">Sub-Services Cost Partition</h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-3 bg-slate-50/50 dark:bg-slate-900/30 border border-slate-150 dark:border-slate-800 rounded-xl">
            <span className="text-[10px] text-slate-400 block font-semibold uppercase">Speech-To-Text</span>
            <span className="text-sm font-bold text-slate-700 dark:text-slate-200 block mt-1">{fmtCost(stats.sttCost)}</span>
          </div>
          <div className="p-3 bg-slate-50/50 dark:bg-slate-900/30 border border-slate-150 dark:border-slate-800 rounded-xl">
            <span className="text-[10px] text-slate-400 block font-semibold uppercase">AI LLM Engines</span>
            <span className="text-sm font-bold text-slate-700 dark:text-slate-200 block mt-1">{fmtCost(stats.llmCost)}</span>
          </div>
          <div className="p-3 bg-slate-50/50 dark:bg-slate-900/30 border border-slate-150 dark:border-slate-800 rounded-xl">
            <span className="text-[10px] text-slate-400 block font-semibold uppercase">Text-To-Speech (TTS)</span>
            <span className="text-sm font-bold text-slate-700 dark:text-slate-200 block mt-1">{fmtCost(stats.ttsCost)}</span>
          </div>
          <div className="p-3 bg-slate-50/50 dark:bg-slate-900/30 border border-slate-150 dark:border-slate-800 rounded-xl">
            <span className="text-[10px] text-slate-400 block font-semibold uppercase">Telephony Routing</span>
            <span className="text-sm font-bold text-slate-700 dark:text-slate-200 block mt-1">{fmtCost(stats.telephonyCost)}</span>
          </div>
        </div>
      </div>

      {/* Breakdown Grid */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-4">
        <h4 className="font-bold text-sm text-slate-800 dark:text-slate-200">Daily cost summaries</h4>
        
        {loading ? (
          <div className="flex items-center justify-center p-8 text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin mr-2 text-violet-500" />
            Recalculating costs...
          </div>
        ) : breakdown.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-6">No cost records found for the active criteria.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Calls</th>
                  <th className="px-4 py-3 text-left">Minutes</th>
                  <th className="px-4 py-3 text-left">STT / LLM</th>
                  <th className="px-4 py-3 text-left">TTS / Telephony</th>
                  <th className="px-4 py-3 text-left">Total Cost</th>
                  <th className="px-4 py-3 text-left">Cost / min</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
                {breakdown.map(row => (
                  <tr key={row.date} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                    <td className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">{row.date}</td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-350">{row.total_calls} calls</td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-350">{row.total_minutes.toFixed(2)}m</td>
                    <td className="px-4 py-3 text-slate-550 dark:text-slate-400 text-xs">
                      <div>STT: {fmtCost(row.stt_cost)}</div>
                      <div>LLM: {fmtCost(row.llm_cost)}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-550 dark:text-slate-400 text-xs">
                      <div>TTS: {fmtCost(row.tts_cost)}</div>
                      <div>TEL: {fmtCost(row.telephony_cost)}</div>
                    </td>
                    <td className="px-4 py-3 font-bold text-slate-900 dark:text-white">{fmtCost(row.total_cost)}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{fmtCost(row.cost_per_minute)}/m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Configured Rates Editor */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
        <div>
          <h4 className="font-bold text-base text-slate-800 dark:text-slate-200">Custom Provider Rates</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Override the default hardcoded calling estimation rates. Cost is calculated per-second of call duration.
          </p>
        </div>

        <form onSubmit={handleAddRate} className="grid grid-cols-1 md:grid-cols-5 gap-4 items-end bg-slate-50/50 dark:bg-slate-900/30 p-4 rounded-xl border border-slate-200 dark:border-slate-850">
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Category</span>
            <select
              value={formCategory}
              onChange={e => setFormCategory(e.target.value)}
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            >
              <option value="stt">Speech-To-Text</option>
              <option value="llm">Language Model</option>
              <option value="tts">Text-To-Speech</option>
              <option value="telephony">Telephony</option>
            </select>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Provider</span>
            <input
              type="text"
              placeholder="e.g. twilio, cartesia, openai"
              value={formProvider}
              onChange={e => setFormProvider(e.target.value.toLowerCase())}
              required
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            />
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Model / Voice</span>
            <input
              type="text"
              placeholder="e.g. aura-asteria-en, gpt-4o"
              value={formModelVoice}
              onChange={e => setFormModelVoice(e.target.value)}
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            />
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Rate per Second (USD)</span>
            <input
              type="number"
              step="0.00000001"
              placeholder="e.g. 0.00000450"
              value={formRatePerSecond}
              onChange={e => setFormRatePerSecond(e.target.value)}
              required
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={submittingRate}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-xs font-bold transition-all h-9 disabled:opacity-50 cursor-pointer"
          >
            {submittingRate ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Add / Update Rate
          </button>
        </form>

        {ratesLoading ? (
          <div className="flex items-center justify-center py-6 text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin mr-2 text-violet-500" />
            Loading rates...
          </div>
        ) : ratesList.length === 0 ? (
          <p className="text-center text-slate-400 text-xs py-4">No custom rates configured. Using live API lookup.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">Category</th>
                  <th className="px-4 py-2.5 text-left">Provider</th>
                  <th className="px-4 py-2.5 text-left">Model / Voice</th>
                  <th className="px-4 py-2.5 text-left">Rate per Second</th>
                  <th className="px-4 py-2.5 text-left">Estimated per Min</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
                {ratesList.map(rate => (
                  <tr key={rate.id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                    <td className="px-4 py-2.5 uppercase font-semibold text-slate-600 dark:text-slate-350">{rate.category}</td>
                    <td className="px-4 py-2.5 text-slate-700 dark:text-slate-200 font-semibold">{rate.provider}</td>
                    <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">{rate.model_or_voice || "—"}</td>
                    <td className="px-4 py-2.5 font-semibold text-slate-700 dark:text-slate-200">${Number(rate.rate_per_second).toFixed(8)}</td>
                    <td className="px-4 py-2.5 text-slate-500">${(Number(rate.rate_per_second) * 60).toFixed(4)}/m</td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => handleDeleteRate(rate.id)}
                        className="text-red-500 hover:text-red-700 text-xs font-semibold px-2 py-1 rounded hover:bg-red-50/50 dark:hover:bg-red-950/20 transition-all cursor-pointer"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
