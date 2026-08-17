"use client";

import { useCallback, useState } from "react";
import {
  GitBranch,
  Loader2,
  Plus,
  Save,
  Trash2,
  X,
  Volume2,
  Zap,
  Route,
  Workflow,
} from "lucide-react";
import clsx from "clsx";

/* ─── Types ─── */

type EdgeConditionType = "llm" | "expression" | "event" | "unconditional";

type GraphEdge = {
  to_node_id: string;
  condition?: string;
  condition_type: EdgeConditionType;
  priority: number;
};

type GraphNode = {
  id: string;
  prompt?: string;
  node_type: "llm" | "static";
  static_message?: string;
  edges: GraphEdge[];
  examples?: Record<string, string>;
  repeat_after_silence_seconds?: number;
  function_call?: string;
};

type GraphConfig = {
  agent_type: string;
  agent_information?: string;
  routing_instructions?: string;
  current_node_id: string;
  nodes: GraphNode[];
  model?: string;
  routing_model?: string;
  routing_max_tokens: number;
};

/* ─── Props ─── */

type Props = {
  graphJson: string;
  onChange: (json: string) => void;
  onSave: () => void;
  saving: boolean;
};

export default function GraphEditor({ graphJson, onChange, onSave, saving }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeIdx, setSelectedEdgeIdx] = useState<number | null>(null);

  const config: GraphConfig | null = (() => {
    try {
      const parsed = JSON.parse(graphJson);
      if (!parsed || !Array.isArray(parsed.nodes)) return null;
      return parsed;
    } catch {
      return null;
    }
  })();

  const updateConfig = useCallback(
    (updater: (prev: GraphConfig) => GraphConfig) => {
      try {
        const current = JSON.parse(graphJson);
        const updated = updater(current);
        onChange(JSON.stringify(updated, null, 2));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Invalid JSON");
      }
    },
    [graphJson, onChange],
  );

  const addNode = () => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: [
        ...cfg.nodes,
        {
          id: `node_${cfg.nodes.length + 1}`,
          prompt: "Enter your node prompt here...",
          node_type: "llm",
          edges: [],
        },
      ],
    }));
  };

  const removeNode = (nodeId: string) => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: cfg.nodes.filter((n) => n.id !== nodeId),
      current_node_id: cfg.current_node_id === nodeId
        ? (cfg.nodes.find((n) => n.id !== nodeId)?.id || cfg.current_node_id)
        : cfg.current_node_id,
    }));
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
  };

  const updateNode = (nodeId: string, patch: Partial<GraphNode>) => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: cfg.nodes.map((n) => (n.id === nodeId ? { ...n, ...patch } : n)),
    }));
  };

  const addEdge = (nodeId: string) => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: cfg.nodes.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              edges: [
                ...n.edges,
                {
                  to_node_id: cfg.nodes.find((m) => m.id !== nodeId)?.id || "",
                  condition_type: "llm" as EdgeConditionType,
                  condition: "",
                  priority: 100,
                },
              ],
            }
          : n,
      ),
    }));
  };

  const removeEdge = (nodeId: string, edgeIdx: number) => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: cfg.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, edges: n.edges.filter((_, i) => i !== edgeIdx) }
          : n,
      ),
    }));
    setSelectedEdgeIdx(null);
  };

  const updateEdge = (nodeId: string, edgeIdx: number, patch: Partial<GraphEdge>) => {
    updateConfig((cfg) => ({
      ...cfg,
      nodes: cfg.nodes.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              edges: n.edges.map((e, i) => (i === edgeIdx ? { ...e, ...patch } : e)),
            }
          : n,
      ),
    }));
  };

  const selectedNode = config?.nodes.find((n) => n.id === selectedNodeId);

  const edgeTypeIcons: Record<EdgeConditionType, typeof Route> = {
    llm: Zap,
    expression: Route,
    event: Workflow,
    unconditional: GitBranch,
  };

  if (!config) {
    return (
      <div className="space-y-5 rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
        <textarea
          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-3 font-mono text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-[520px]"
          value={graphJson}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Paste graph agent JSON config..."
        />
        <div className="flex items-center gap-3">
          <button 
            onClick={onSave} 
            disabled={saving} 
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-6 py-3 text-xs font-bold text-white shadow-lg shadow-violet-500/25 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/35 active:scale-98 transition-all disabled:opacity-60 cursor-pointer"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save Graph
          </button>
          {error && <p className="text-sm font-semibold text-red-500">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3.5 bg-white/40 dark:bg-slate-900/30 p-4 rounded-2xl border border-slate-200/50 dark:border-slate-800/30 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <button 
            onClick={addNode} 
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:border-slate-700 shadow-sm transition-all duration-200 active:scale-95 cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5 text-violet-500" /> Add Node
          </button>
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{config.nodes.length} nodes</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            Start Node:
          </span>
          <select
            className="rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs font-semibold outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
            value={config.current_node_id}
            onChange={(e) => updateConfig((cfg) => ({ ...cfg, current_node_id: e.target.value }))}
          >
            {config.nodes.map((n) => (
              <option key={n.id} value={n.id}>{n.id}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50/60 px-5 py-4 text-xs font-medium text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300 backdrop-blur-sm">
          {error}
        </div>
      )}

      {/* Main layout: node list + node editor */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_420px]">
        {/* Node list */}
        <div className="space-y-4">
          {config.nodes.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 dark:border-slate-800/80 p-12 text-center text-sm font-semibold text-slate-400">
              No nodes yet. Click "Add Node" to start building your conversation graph.
            </div>
          ) : (
            config.nodes.map((node) => (
              <div
                key={node.id}
                className={clsx(
                  "rounded-2xl border p-5 transition-all duration-300 shadow-sm backdrop-blur-sm",
                  selectedNodeId === node.id
                    ? "border-violet-500/30 bg-gradient-to-br from-violet-500/10 via-indigo-500/5 to-transparent dark:from-violet-500/20 dark:via-indigo-500/10 dark:to-transparent ring-2 ring-violet-500/10 shadow-sm"
                    : "border-slate-200/60 bg-white/60 hover:border-violet-200/50 hover:bg-violet-50/10 dark:border-slate-800/40 dark:bg-slate-900/40 dark:hover:border-violet-900/20 dark:hover:bg-violet-950/5",
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span
                      className="cursor-pointer font-mono text-sm font-bold text-slate-800 dark:text-slate-200 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
                      onClick={() => setSelectedNodeId(node.id)}
                    >
                      {node.id}
                    </span>
                    <span className={clsx(
                      "rounded-lg px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      node.node_type === "static"
                        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                        : "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
                    )}>
                      {node.node_type}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => setSelectedNodeId(node.id)}
                      className="rounded-lg p-1.5 text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:text-violet-400 dark:hover:bg-violet-950/20 transition-all cursor-pointer"
                      title="Edit node"
                    >
                      <Volume2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => removeNode(node.id)}
                      className="rounded-lg p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50/50 dark:hover:text-red-400 dark:hover:bg-red-950/20 transition-all cursor-pointer"
                      title="Delete node"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {/* Edge list */}
                {node.edges.length > 0 && (
                  <div className="mt-3.5 space-y-2">
                    {node.edges.map((edge, ei) => {
                      const EdgeIcon = edgeTypeIcons[edge.condition_type];
                      return (
                        <div
                          key={ei}
                          className={clsx(
                            "flex items-center justify-between rounded-xl px-3.5 py-2.5 text-xs backdrop-blur-sm",
                            selectedEdgeIdx === ei && selectedNodeId === node.id
                              ? "ring-2 ring-violet-500/25 border border-violet-500/30 bg-violet-50/10 dark:bg-violet-950/5"
                              : "border border-slate-100/50 dark:border-slate-800/20 bg-slate-50/40 dark:bg-slate-800/30",
                          )}
                        >
                          <div className="flex items-center gap-2">
                            <EdgeIcon className="h-3.5 w-3.5 text-violet-500/70" />
                            <span className="font-mono font-bold text-violet-600 dark:text-violet-400">
                              → {edge.to_node_id}
                            </span>
                            <span className="text-slate-400 font-medium">({edge.condition_type})</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => {
                                setSelectedNodeId(node.id);
                                setSelectedEdgeIdx(ei);
                              }}
                              className="text-slate-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors p-1 cursor-pointer"
                            >
                              <Volume2 className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => removeEdge(node.id, ei)}
                              className="text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors p-1 cursor-pointer"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                <button
                  onClick={() => addEdge(node.id)}
                  className="mt-3 inline-flex items-center gap-1 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-slate-500 hover:text-violet-600 hover:bg-violet-50/50 dark:text-slate-400 dark:hover:text-violet-400 dark:hover:bg-violet-950/25 transition-all cursor-pointer"
                >
                  <Plus className="h-3.5 w-3.5" /> Add edge
                </button>
              </div>
            ))
          )}
        </div>

        {/* Node editor panel */}
        {selectedNode ? (
          <div className="space-y-5 rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100/50 dark:border-slate-800/40">
              <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Edit: {selectedNode.id}</h3>
              <button onClick={() => setSelectedNodeId(null)} className="text-slate-450 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-450 transition-colors cursor-pointer">
                <X className="h-4 w-4" />
              </button>
            </div>

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Node Type</span>
              <select
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                value={selectedNode.node_type}
                onChange={(e) => updateNode(selectedNode.id, { node_type: e.target.value as "llm" | "static" })}
              >
                <option value="llm">LLM (AI-generated response)</option>
                <option value="static">Static (pre-cached audio, zero LLM cost)</option>
              </select>
            </label>

            {selectedNode.node_type === "static" ? (
              <label className="block">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Static Message</span>
                <textarea
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-20"
                  value={selectedNode.static_message || ""}
                  onChange={(e) => updateNode(selectedNode.id, { static_message: e.target.value })}
                  placeholder="Message that plays without LLM (50ms latency)"
                />
              </label>
            ) : (
              <>
                <label className="block">
                  <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Prompt</span>
                  <textarea
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-xs font-mono outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-32"
                    value={selectedNode.prompt || ""}
                    onChange={(e) => updateNode(selectedNode.id, { prompt: e.target.value })}
                    placeholder="Instructions for the LLM at this node"
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Function Call (tool_choice)</span>
                  <input
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
                    value={selectedNode.function_call || ""}
                    onChange={(e) => updateNode(selectedNode.id, { function_call: e.target.value })}
                    placeholder="e.g. transfer_call, or 'auto' for automatic"
                  />
                </label>
              </>
            )}

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">
                Repeat After Silence (seconds)
              </span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={0}
                step={1}
                value={selectedNode.repeat_after_silence_seconds ?? ""}
                onChange={(e) =>
                  updateNode(selectedNode.id, {
                    repeat_after_silence_seconds: e.target.value ? Number(e.target.value) : undefined,
                  })
                }
                placeholder="Auto-replay if user is silent"
              />
            </label>

            {/* Edge editor */}
            {selectedEdgeIdx !== null && selectedNode.edges[selectedEdgeIdx] && (
              <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-850/50 space-y-3.5">
                <h4 className="text-xs font-bold text-violet-600 dark:text-violet-400 uppercase tracking-wide">
                  Edge → {selectedNode.edges[selectedEdgeIdx].to_node_id}
                </h4>

                <label className="block">
                  <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Condition Type</span>
                  <select
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                    value={selectedNode.edges[selectedEdgeIdx].condition_type}
                    onChange={(e) =>
                      updateEdge(selectedNode.id, selectedEdgeIdx, {
                        condition_type: e.target.value as EdgeConditionType,
                      })
                    }
                  >
                    <option value="llm">LLM-decided</option>
                    <option value="expression">Expression (deterministic)</option>
                    <option value="event">Event (external trigger)</option>
                    <option value="unconditional">Unconditional (always follow)</option>
                  </select>
                </label>

                {selectedNode.edges[selectedEdgeIdx].condition_type === "expression" && (
                  <label className="block">
                    <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Expression (JSON)</span>
                    <textarea
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 font-mono text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-16"
                      value={selectedNode.edges[selectedEdgeIdx].condition || ""}
                      onChange={(e) =>
                        updateEdge(selectedNode.id, selectedEdgeIdx, { condition: e.target.value })
                      }
                      placeholder='{"gte": ["retry_count", 3]}'
                    />
                  </label>
                )}

                {selectedNode.edges[selectedEdgeIdx].condition_type === "llm" && (
                  <label className="block">
                    <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">LLM Condition Prompt</span>
                    <input
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                      value={selectedNode.edges[selectedEdgeIdx].condition || ""}
                      onChange={(e) =>
                        updateEdge(selectedNode.id, selectedEdgeIdx, { condition: e.target.value })
                      }
                      placeholder="e.g. Customer provides a valid order number"
                    />
                  </label>
                )}

                <label className="block">
                  <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Target Node</span>
                  <select
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                    value={selectedNode.edges[selectedEdgeIdx].to_node_id}
                    onChange={(e) =>
                      updateEdge(selectedNode.id, selectedEdgeIdx, { to_node_id: e.target.value })
                    }
                  >
                    {config.nodes
                      .filter((n) => n.id !== selectedNode.id)
                      .map((n) => (
                        <option key={n.id} value={n.id}>{n.id}</option>
                      ))}
                  </select>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Priority (lower = first)</span>
                  <input
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
                    type="number"
                    min={0}
                    value={selectedNode.edges[selectedEdgeIdx].priority}
                    onChange={(e) =>
                      updateEdge(selectedNode.id, selectedEdgeIdx, { priority: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
            )}

            {/* Examples */}
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Examples (per-language)</span>
              <textarea
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 font-mono text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-16"
                value={JSON.stringify(selectedNode.examples || {}, null, 2)}
                onChange={(e) => {
                  try {
                    updateNode(selectedNode.id, { examples: JSON.parse(e.target.value) });
                  } catch {
                    // allow editing
                  }
                }}
                placeholder='{"en": "Sure, let me check that for you.", "hi": "..."}'
              />
            </label>
          </div>
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-dashed border-slate-200 dark:border-slate-800/80 p-12 text-center text-sm font-semibold text-slate-400">
            Select a node to edit its configuration
          </div>
        )}
      </div>

      {/* Agent info */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Agent Information (global persona)</span>
            <textarea
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-24"
              value={config.agent_information || ""}
              onChange={(e) => updateConfig((cfg) => ({ ...cfg, agent_information: e.target.value }))}
              placeholder="Persona, language rules, guardrails — applied to every node"
            />
          </label>
        </div>
        <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Routing Instructions</span>
            <textarea
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-24"
              value={config.routing_instructions || ""}
              onChange={(e) => updateConfig((cfg) => ({ ...cfg, routing_instructions: e.target.value }))}
              placeholder="Instructions for the routing LLM"
            />
          </label>
        </div>
      </div>

      {/* Model config */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-slate-400">LLM Routing Configurations</h3>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <label className="block">
            <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Response Model</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              value={config.model || ""}
              onChange={(e) => updateConfig((cfg) => ({ ...cfg, model: e.target.value }))}
              placeholder="Default: gpt-4.1-mini"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Routing Model (cheaper)</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              value={config.routing_model || ""}
              onChange={(e) => updateConfig((cfg) => ({ ...cfg, routing_model: e.target.value }))}
              placeholder="Default: gpt-4.1-mini"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Routing Max Tokens</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
              type="number"
              min={50}
              value={config.routing_max_tokens}
              onChange={(e) => updateConfig((cfg) => ({ ...cfg, routing_max_tokens: Number(e.target.value) }))}
            />
          </label>
        </div>
      </div>

      {/* Save button */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-2">
        <button 
          onClick={onSave} 
          disabled={saving} 
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-6 py-3 text-xs font-bold text-white shadow-lg shadow-violet-500/25 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/35 active:scale-98 transition-all disabled:opacity-60 cursor-pointer"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Graph Config
        </button>
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Nodes: {config.nodes.length} | Edges: {config.nodes.reduce((s, n) => s + n.edges.length, 0)}
        </span>
      </div>
    </div>
  );
}
