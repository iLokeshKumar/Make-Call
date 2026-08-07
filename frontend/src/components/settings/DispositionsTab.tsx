"use client";

import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, Plus, Trash2, Edit2, Play, Loader2, AlertCircle, Sparkles, HelpCircle } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE, CRM_BASE } from "@/lib/api";

type VoiceAgent = {
  id: number;
  name: string;
  agent_type: string;
};

type Disposition = {
  id: number;
  agent_id: number;
  key: string;
  label: string;
  description?: string | null;
  instructions?: string | null;
  is_active: boolean;
};

export default function DispositionsTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [agents, setAgents] = useState<VoiceAgent[]>([]);
  const [dispositions, setDispositions] = useState<Disposition[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<number | "all">("all");
  const [loading, setLoading] = useState(true);
  
  // Modal State
  const [showModal, setShowModal] = useState(false);
  const [editingDisp, setEditingDisp] = useState<Disposition | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [modalSaving, setModalSaving] = useState(false);
  const [form, setForm] = useState({
    agent_id: "",
    key: "",
    label: "",
    description: "",
    instructions: "",
    is_active: true,
  });

  // Testing State
  const [testTranscript, setTestTranscript] = useState("Agent: Hello, would you like a demo?\nCustomer: Yes, please send me the booking calendar link!");
  const [testKey, setTestKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [agentsRes, dispsRes] = await Promise.all([
        apiFetch(`${CRM_BASE}/voice-agents`),
        apiFetch(`${CRM_BASE}/dispositions`),
      ]);
      if (agentsRes.status === 401 || dispsRes.status === 401) {
        sessionTimeout();
        return;
      }
      
      let loadedAgents: VoiceAgent[] = [];
      if (agentsRes.ok) {
        const data = await agentsRes.json();
        // The API returns list of objects containing the agent directly, or direct agent objects
        loadedAgents = Array.isArray(data) ? data.map(item => item.agent || item) : [];
        setAgents(loadedAgents);
      }
      
      if (dispsRes.ok) {
        setDispositions(await dispsRes.json());
      }
    } catch (e) {
      console.error("Failed to load dispositions tab data", e);
    } finally {
      setLoading(false);
    }
  }, [sessionTimeout]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openCreateModal = () => {
    setEditingDisp(null);
    setForm({
      agent_id: agents.length > 0 ? String(agents[0].id) : "",
      key: "",
      label: "",
      description: "",
      instructions: "",
      is_active: true,
    });
    setModalError(null);
    setShowModal(true);
  };

  const openEditModal = (disp: Disposition) => {
    setEditingDisp(disp);
    setForm({
      agent_id: String(disp.agent_id),
      key: disp.key,
      label: disp.label,
      description: disp.description || "",
      instructions: disp.instructions || "",
      is_active: disp.is_active,
    });
    setModalError(null);
    setShowModal(true);
  };

  const saveDisposition = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalSaving(true);
    setModalError(null);
    try {
      const isNew = editingDisp === null;
      const url = isNew 
        ? `${CRM_BASE}/dispositions?agent_id=${form.agent_id}` 
        : `${CRM_BASE}/dispositions/${editingDisp.id}`;
      
      const payload = isNew 
        ? {
            key: form.key.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_"),
            label: form.label.trim(),
            description: form.description.trim() || null,
            instructions: form.instructions.trim() || null,
            is_active: form.is_active,
          }
        : {
            label: form.label.trim(),
            description: form.description.trim() || null,
            instructions: form.instructions.trim() || null,
            is_active: form.is_active,
          };

      const res = await apiFetch(url, {
        method: isNew ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to save outcome disposition.");
      }

      setShowModal(false);
      fetchData();
    } catch (err) {
      setModalError(err instanceof Error ? err.message : "Error saving");
    } finally {
      setModalSaving(false);
    }
  };

  const deleteDisposition = async (id: number) => {
    if (!window.confirm("Delete this disposition outcome trigger?")) return;
    try {
      const res = await apiFetch(`${CRM_BASE}/dispositions/${id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setDispositions(prev => prev.filter(d => d.id !== id));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const runTestClassification = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!testTranscript.trim() || !testKey.trim()) return;
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const res = await apiFetch(`${CRM_BASE}/dispositions/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript: testTranscript.trim(),
          disposition_key: testKey.trim(),
        }),
      });
      if (res.ok) {
        setTestResult(await res.json());
      } else {
        const body = await res.json().catch(() => ({}));
        setTestError(body.detail || "Classification test failed.");
      }
    } catch (err) {
      setTestError("Network error during test execution");
    } finally {
      setTesting(false);
    }
  };

  const filteredDisps = selectedAgentId === "all"
    ? dispositions
    : dispositions.filter(d => d.agent_id === Number(selectedAgentId));

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-violet-500" />
        Loading call outcome triggers...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* List / Management section */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600">
              <CheckCircle2 className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Outcome Dispositions</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Instruct AI agents how to classify outcomes based on final call transcripts</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={selectedAgentId}
              onChange={e => setSelectedAgentId(e.target.value === "all" ? "all" : Number(e.target.value))}
              className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
            >
              <option value="all">All Voice Agents</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <button
              onClick={openCreateModal}
              disabled={agents.length === 0}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors disabled:opacity-50"
            >
              <Plus className="h-4 w-4" /> Add Outcome Trigger
            </button>
          </div>
        </div>

        {filteredDisps.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-8">No dispositions configured for the selected agent. Add one to start tracking outcomes.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {filteredDisps.map(disp => {
              const agentName = agents.find(a => a.id === disp.agent_id)?.name ?? "Unknown Agent";
              return (
                <div key={disp.id} className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/30 flex flex-col justify-between space-y-4">
                  <div>
                    <div className="flex items-start justify-between">
                      <div>
                        <span className="text-xs font-bold font-mono text-violet-600 dark:text-violet-400 uppercase bg-violet-50 dark:bg-violet-950/30 px-2 py-0.5 rounded">
                          {disp.key}
                        </span>
                        <h4 className="font-bold text-slate-800 dark:text-slate-200 mt-2">{disp.label}</h4>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${disp.is_active ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300" : "bg-slate-100 text-slate-500"}`}>
                        {disp.is_active ? "active" : "disabled"}
                      </span>
                    </div>

                    <p className="text-xs text-slate-400 mt-1">Agent: <span className="font-medium text-slate-600 dark:text-slate-300">{agentName}</span></p>
                    
                    {disp.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">{disp.description}</p>
                    )}

                    {disp.instructions && (
                      <div className="bg-slate-50 dark:bg-slate-800/40 p-3 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-400 mt-3 border border-slate-200/50 dark:border-slate-850">
                        <span className="font-bold text-slate-700 dark:text-slate-300 block mb-1">Classification Instructions:</span>
                        {disp.instructions}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-3 pt-3 border-t border-slate-150 dark:border-slate-800/60">
                    <button
                      onClick={() => openEditModal(disp)}
                      className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-violet-600 transition-colors"
                    >
                      <Edit2 className="h-3.5 w-3.5" /> Edit
                    </button>
                    <button
                      onClick={() => {
                        setTestKey(disp.key);
                        const element = document.getElementById("test-classification-sec");
                        if (element) element.scrollIntoView({ behavior: "smooth" });
                      }}
                      className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-500 transition-colors ml-2"
                    >
                      <Play className="h-3.5 w-3.5" /> Set as Test Key
                    </button>
                    <button
                      onClick={() => deleteDisposition(disp.id)}
                      className="p-1 text-slate-450 hover:text-rose-600 transition-colors ml-auto"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Live Testing Panel */}
      <div id="test-classification-sec" className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Live Outcome Predictor</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">Dry-run your disposition classification prompts on a test transcript in real-time</p>
          </div>
        </div>

        <form onSubmit={runTestClassification} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Test Transcript</label>
              <textarea
                required
                value={testTranscript}
                onChange={e => setTestTranscript(e.target.value)}
                placeholder="Agent: Hi, are you interested in our software?..."
                className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
                rows={5}
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Disposition Key to Test</label>
              <input
                required
                value={testKey}
                onChange={e => setTestKey(e.target.value)}
                placeholder="e.g. interested"
                className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-violet-500 mb-4"
              />
              <button
                type="submit"
                disabled={testing || !testTranscript.trim() || !testKey.trim()}
                className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-750 disabled:opacity-50 transition-colors shadow-md"
              >
                {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Evaluate Outcome
              </button>
            </div>
          </div>
        </form>

        {testError && (
          <div className="text-sm text-rose-600 bg-rose-50 dark:bg-rose-950/30 rounded-lg p-3 max-w-xl flex items-center gap-2">
            <AlertCircle className="h-4 w-4" /> {testError}
          </div>
        )}

        {testResult && (
          <div className="p-5 rounded-xl border border-blue-200 dark:border-blue-900 bg-blue-50/50 dark:bg-blue-950/20 text-slate-800 dark:text-slate-200 space-y-3">
            <h4 className="font-bold text-sm text-blue-700 dark:text-blue-400 flex items-center gap-1.5">
              <Sparkles className="h-4 w-4" /> Classification Result
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs mt-2 border-t border-slate-200/50 dark:border-slate-800 pt-3">
              <div>
                <span className="text-slate-400 block uppercase font-bold tracking-wider">Classification Match</span>
                <span className={`text-sm font-bold block mt-1 ${testResult.matches ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-450"}`}>
                  {testResult.matches ? "MATCHED (True)" : "NOT MATCHED (False)"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block uppercase font-bold tracking-wider">Confidence Score</span>
                <span className="text-sm font-bold block mt-1 font-mono">{testResult.confidence != null ? `${testResult.confidence}%` : "N/A"}</span>
              </div>
              <div>
                <span className="text-slate-400 block uppercase font-bold tracking-wider">Evaluation Cost</span>
                <span className="text-xs text-slate-400 font-mono block mt-1">Calculated via LLM LLM-as-Judge</span>
              </div>
            </div>
            {testResult.reason && (
              <div className="text-xs bg-white dark:bg-slate-900/60 p-3 rounded-lg border border-slate-250 dark:border-slate-800 mt-2">
                <span className="font-semibold block text-slate-500 dark:text-slate-400 mb-1">Judge Logic Reason:</span>
                {testResult.reason}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modal - Create/Edit Outcome Trigger */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
              <h2 className="font-bold text-slate-900 dark:text-slate-100">
                {editingDisp ? "Edit Outcome Trigger" : "Add Outcome Trigger"}
              </h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={saveDisposition} className="p-6 space-y-4">
              {modalError && (
                <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" /> {modalError}
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                {editingDisp === null && (
                  <>
                    <div>
                      <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Voice Agent</label>
                      <select
                        value={form.agent_id}
                        onChange={e => setForm(p => ({ ...p, agent_id: e.target.value }))}
                        className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                      >
                        {agents.map(a => (
                          <option key={a.id} value={a.id}>{a.name}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Unique Key Code</label>
                      <input
                        required
                        value={form.key}
                        onChange={e => setForm(p => ({ ...p, key: e.target.value }))}
                        placeholder="e.g. demo_booked"
                        className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 font-mono focus:outline-none"
                      />
                    </div>
                  </>
                )}
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Label / Title</label>
                  <input
                    required
                    value={form.label}
                    onChange={e => setForm(p => ({ ...p, label: e.target.value }))}
                    placeholder="e.g. Booked a Product Demo"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Description</label>
                  <input
                    value={form.description}
                    onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
                    placeholder="Brief outcome description for agent analytics dashboards"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Classification Instructions (LLM-as-Judge Prompt)</label>
                  <textarea
                    required
                    value={form.instructions}
                    onChange={e => setForm(p => ({ ...p, instructions: e.target.value }))}
                    placeholder="Provide explicit instructions for the judge. E.g. 'Classify as true if the customer explicitly agreed to a follow up call next Tuesday or asked for a calendar link.'"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                    rows={4}
                  />
                </div>
                <div className="col-span-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="is_active_trigger"
                    checked={form.is_active}
                    onChange={e => setForm(p => ({ ...p, is_active: e.target.checked }))}
                    className="rounded text-violet-600 focus:ring-violet-500 h-4 w-4"
                  />
                  <label htmlFor="is_active_trigger" className="text-sm text-slate-700 dark:text-slate-300 font-semibold select-none">
                    Enable outcome trigger immediately
                  </label>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-850">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm text-slate-500"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={modalSaving || !form.label.trim() || (editingDisp === null && !form.key.trim())}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
                >
                  {modalSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save Outcome"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
