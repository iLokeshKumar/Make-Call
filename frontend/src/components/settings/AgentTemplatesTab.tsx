"use client";

import { useEffect, useState, useCallback } from "react";
import { Sparkles, Plus, Check, Loader2, AlertCircle, FileText, ChevronDown, ChevronUp, Bot } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");
const CRM_BASE = `${API_BASE}/crm`;

type AgentTemplate = {
  id: number;
  name: string;
  description?: string | null;
  category: string;     // sales, support, collection etc.
  industry: string;     // finance, real_estate, SaaS, edtech etc.
  system_prompt: string;
  default_runtime_json?: Record<string, any> | null;
  is_active: boolean;
};

export default function AgentTemplatesTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [expandedPromptId, setExpandedPromptId] = useState<number | null>(null);

  // Deploy Modal State
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null);
  const [deployName, setDeployName] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [deploySuccess, setDeploySuccess] = useState<string | null>(null);

  // Filters
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedIndustry, setSelectedIndustry] = useState<string>("all");

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${CRM_BASE}/agent-templates`);
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setTemplates(await res.json());
      }
    } catch (e) {
      console.error("Failed to load agent templates", e);
    } finally {
      setLoading(false);
    }
  }, [sessionTimeout]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleSeed = async () => {
    setSeeding(true);
    try {
      const res = await apiFetch(`${CRM_BASE}/agent-templates/seed`, { method: "POST" });
      if (res.ok) {
        fetchTemplates();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSeeding(false);
    }
  };

  const handleDeploy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTemplate || !deployName.trim()) return;
    setDeploying(true);
    setDeployError(null);
    setDeploySuccess(null);
    try {
      const res = await apiFetch(
        `${CRM_BASE}/agent-templates/${selectedTemplate.id}/deploy?agent_name=${encodeURIComponent(deployName.trim())}`,
        { method: "POST" }
      );
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setDeploySuccess(`Deployed agent "${deployName.trim()}" successfully!`);
        setDeployName("");
        setTimeout(() => {
          setSelectedTemplate(null);
          setDeploySuccess(null);
        }, 3000);
      } else {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to deploy agent from template");
      }
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Deployment failed");
    } finally {
      setDeploying(false);
    }
  };

  // Get unique categories and industries for filter dropdowns
  const categories = ["all", ...Array.from(new Set(templates.map(t => t.category)))];
  const industries = ["all", ...Array.from(new Set(templates.map(t => t.industry)))];

  const filteredTemplates = templates.filter(t => {
    const catMatch = selectedCategory === "all" || t.category === selectedCategory;
    const indMatch = selectedIndustry === "all" || t.industry === selectedIndustry;
    return catMatch && indMatch;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-violet-500" />
        Loading agent templates...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header and filters */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">AI Voice Agent Templates</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Deploy pre-configured prompt architectures tailored by industry and use-case</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {templates.length === 0 && (
              <button
                onClick={handleSeed}
                disabled={seeding}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {seeding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Seed Default Templates
              </button>
            )}
            
            <div className="flex items-center gap-2">
              <select
                value={selectedCategory}
                onChange={e => setSelectedCategory(e.target.value)}
                className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
              >
                {categories.map(c => (
                  <option key={c} value={c} className="capitalize">{c === "all" ? "All Categories" : c}</option>
                ))}
              </select>
              <select
                value={selectedIndustry}
                onChange={e => setSelectedIndustry(e.target.value)}
                className="p-2 rounded-lg border border-slate-350 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-200 focus:outline-none"
              >
                {industries.map(i => (
                  <option key={i} value={i} className="capitalize">{i === "all" ? "All Industries" : i}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {filteredTemplates.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-8">No templates matched the filters. Seed templates or try a different filter combination.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {filteredTemplates.map((tmpl) => {
              const isExpanded = expandedPromptId === tmpl.id;
              return (
                <div key={tmpl.id} className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/30 flex flex-col justify-between space-y-4">
                  <div className="space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="font-bold text-slate-800 dark:text-slate-200 text-sm">{tmpl.name}</h4>
                        <div className="flex gap-2 mt-1.5">
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-violet-50 text-violet-600 dark:bg-violet-950/30 dark:text-violet-400 uppercase">
                            {tmpl.category}
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400 uppercase">
                            {tmpl.industry}
                          </span>
                        </div>
                      </div>
                    </div>

                    {tmpl.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400">{tmpl.description}</p>
                    )}

                    <div className="border border-slate-200/60 dark:border-slate-800/80 rounded-lg overflow-hidden">
                      <button
                        onClick={() => setExpandedPromptId(isExpanded ? null : tmpl.id)}
                        className="w-full flex items-center justify-between p-2.5 bg-slate-50/50 dark:bg-slate-800/20 text-xs font-semibold text-slate-650 dark:text-slate-350 hover:bg-slate-100 dark:hover:bg-slate-800/50 transition-colors"
                      >
                        <span className="flex items-center gap-1.5"><FileText className="h-3.5 w-3.5" /> System Prompt Blueprint</span>
                        {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      </button>
                      {isExpanded && (
                        <pre className="p-3 text-[11px] font-mono text-slate-650 dark:text-slate-350 bg-slate-50/20 dark:bg-slate-900/30 border-t border-slate-200/50 dark:border-slate-800 max-h-48 overflow-y-auto whitespace-pre-wrap">
                          {tmpl.system_prompt}
                        </pre>
                      )}
                    </div>
                  </div>

                  <div className="flex justify-end pt-3 border-t border-slate-150 dark:border-slate-800/60">
                    <button
                      onClick={() => {
                        setSelectedTemplate(tmpl);
                        setDeployName(tmpl.name);
                        setDeployError(null);
                        setDeploySuccess(null);
                      }}
                      className="flex items-center gap-1.5 px-4 py-2 bg-violet-600 hover:bg-violet-750 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors"
                    >
                      <Bot className="h-3.5 w-3.5" /> Deploy Agent Blueprint
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Deploy Modal */}
      {selectedTemplate && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-md w-full overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
              <h2 className="font-bold text-slate-900 dark:text-slate-100">Deploy AI Agent</h2>
              <button onClick={() => setSelectedTemplate(null)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleDeploy} className="p-6 space-y-4">
              {deployError && (
                <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" /> {deployError}
                </div>
              )}
              {deploySuccess && (
                <div className="text-sm text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 rounded-lg p-3 flex items-center gap-2">
                  <Check className="h-4 w-4" /> {deploySuccess}
                </div>
              )}

              <div className="space-y-1">
                <span className="text-xs text-slate-400 block font-semibold">TEMPLATE SOURCE</span>
                <span className="text-sm font-bold block text-slate-800 dark:text-slate-200">{selectedTemplate.name}</span>
                <span className="text-xs text-slate-400 block capitalize">Category: {selectedTemplate.category} · Industry: {selectedTemplate.industry}</span>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">New Agent Name</label>
                <input
                  required
                  value={deployName}
                  onChange={e => setDeployName(e.target.value)}
                  placeholder="e.g. Inbound Sales Representative"
                  className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-850">
                <button
                  type="button"
                  onClick={() => setSelectedTemplate(null)}
                  className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={deploying || !deployName.trim() || deploySuccess !== null}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-750 disabled:opacity-50"
                >
                  {deploying ? <Loader2 className="h-4 w-4 animate-spin" /> : "Deploy Agent"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
