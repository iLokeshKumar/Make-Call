"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen, Search, Plus, Trash2, RotateCcw, X, Loader2,
  Database, FileText, Shield, Users, Lightbulb, Cpu, Mic,
  ChevronDown, ChevronUp, Sparkles, Send } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// Types

type KBDoc = {
  id: number;
  collection: string;
  title: string;
  content: string;
  tags: string[] | null;
  is_active: boolean;
  last_indexed_at: string | null;
};

type SearchResult = {
  id?: string;
  text: string;
  score: number;
  metadata?: Record<string, unknown>;
};

type AskResult = {
  output: string;
  agents_run?: string[];
  errors?: string[];
};

// Collection config

const COLLECTION_CONFIG: Record<string, { label: string; icon: React.ElementType; color: string; desc: string }> = {
  products:    { label: "Products",    icon: Database,   color: "violet", desc: "Product specs, pricing, features" },
  objections:  { label: "Objections",  icon: Shield,     color: "red",    desc: "Objection handling guides" },
  competitors: { label: "Competitors", icon: Users,      color: "orange", desc: "Competitor battle cards" },
  playbooks:   { label: "Playbooks",   icon: BookOpen,   color: "blue",   desc: "Sales scripts & discovery frameworks" },
  coaching:    { label: "Coaching",    icon: Lightbulb,  color: "amber",  desc: "Coaching tips & best practices" },
  sops:        { label: "SOPs",        icon: Cpu,        color: "green",  desc: "Standard operating procedures" },
  transcripts: { label: "Transcripts", icon: Mic,        color: "slate",  desc: "Auto-indexed past call transcripts" } };

const ALL_COLLECTIONS = Object.keys(COLLECTION_CONFIG);

const colorClasses: Record<string, string> = {
  violet: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300 border-violet-200 dark:border-violet-500/20",
  red:    "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300 border-red-200 dark:border-red-500/20",
  orange: "bg-orange-100 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300 border-orange-200 dark:border-orange-500/20",
  blue:   "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300 border-blue-200 dark:border-blue-500/20",
  amber:  "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300 border-amber-200 dark:border-amber-500/20",
  green:  "bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-300 border-green-200 dark:border-green-500/20",
  slate:  "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-white/10" };

function CollectionBadge({ collection }: { collection: string }) {
  const cfg = COLLECTION_CONFIG[collection];
  if (!cfg) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">{collection}</span>;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${colorClasses[cfg.color]}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}



export default function KnowledgePage() {
  const { user, sessionTimeout } = useAuth();


  const [searchQuery, setSearchQuery] = useState("");
  const [searchCollection, setSearchCollection] = useState("all");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const searchTimerRef = useRef<NodeJS.Timeout | null>(null);


  const [docs, setDocs] = useState<KBDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [filterCollection, setFilterCollection] = useState<string>("all");
  const [expandedDoc, setExpandedDoc] = useState<number | null>(null);


  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ collection: "products", title: "", content: "", tags: "" });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");


  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");


  const [askQuery, setAskQuery] = useState("");
  const [askLoading, setAskLoading] = useState(false);
  const [askResult, setAskResult] = useState<AskResult | null>(null);

  // RAG preview — raw retrieval (no LLM), shows top chunks + scores so admins
  // can verify what the agent will actually see for a given query.
  const [ragQuery, setRagQuery] = useState("");
  const [ragLoading, setRagLoading] = useState(false);
  const [ragResults, setRagResults] = useState<Array<{ content: string; collection?: string; score?: number; metadata?: Record<string, unknown> }>>([]);
  const [ragError, setRagError] = useState<string | null>(null);

  async function handleRagPreview(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !ragQuery.trim()) return;
    setRagLoading(true);
    setRagError(null);
    setRagResults([]);
    try {
      const params = new URLSearchParams({ q: ragQuery.trim(), n: "5", collection: filterCollection });
      const res = await apiFetch(`${API_BASE}/crm/knowledge/search?${params}`);
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRagResults(data.results || []);
    } catch (err) {
      setRagError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setRagLoading(false);
    }
  }

  // Fetch documents

  const fetchDocs = useCallback(async () => {
    if (!user) return;
    setDocsLoading(true);
    try {
      const col = filterCollection !== "all" ? `?collection=${filterCollection}&active_only=false` : "?active_only=false";
      const res = await apiFetch(`${API_BASE}/crm/knowledge/documents${col}`, {
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load documents");
      setDocs(await res.json());
    } catch {
      // silently ignore — we'll show empty state
    } finally {
      setDocsLoading(false);
    }
  }, [user, sessionTimeout, filterCollection]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  // Semantic search (debounced 400 ms)

  const runSearch = useCallback(async (q: string, col: string) => {
    if (!q.trim() ) { setSearchResults([]); return; }
    setSearching(true);
    setSearchError("");
    try {
      const params = new URLSearchParams({ q, collection: col, n: "8" });
      const res = await apiFetch(`${API_BASE}/crm/knowledge/search?${params}`, {
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setSearchResults(data.results ?? []);
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }, [user, sessionTimeout]);

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!searchQuery.trim()) { setSearchResults([]); return; }
    searchTimerRef.current = setTimeout(() => runSearch(searchQuery, searchCollection), 400);
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current); };
  }, [searchQuery, searchCollection, runSearch]);

  // Add document

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !addForm.title.trim() || !addForm.content.trim()) return;
    setAdding(true);
    setAddError("");
    try {
      const tags = addForm.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await apiFetch(`${API_BASE}/crm/knowledge/documents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          collection: addForm.collection,
          title: addForm.title.trim(),
          content: addForm.content.trim(),
          tags: tags.length ? tags : null }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.detail || "Create failed");
      }
      setShowAdd(false);
      setAddForm({ collection: "products", title: "", content: "", tags: "" });
      await fetchDocs();
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setAdding(false);
    }
  }

  // Delete document

  async function handleDelete(id: number) {
    if (!user || !window.confirm("Remove this document from the knowledge base?")) return;
    try {
      const res = await apiFetch(`${API_BASE}/crm/knowledge/documents/${id}`, {
        method: "DELETE"
      });
      if (res.status === 401) { sessionTimeout(); return; }
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch {

    }
  }

  // Reindex

  async function handleReindex() {
    if (!user) return;
    setReindexing(true);
    setReindexMsg("");
    try {
      const res = await apiFetch(`${API_BASE}/crm/knowledge/reindex`, {
        method: "POST"
      });
      if (!res.ok) throw new Error("Reindex failed");
      const data = await res.json();
      setReindexMsg(`Reindexed ${data.reindexed} document(s) successfully.`);
      await fetchDocs();
    } catch {
      setReindexMsg("Reindex failed — check backend logs.");
    } finally {
      setReindexing(false);
    }
  }

  // Ask Rio

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !askQuery.trim()) return;
    setAskLoading(true);
    setAskResult(null);
    try {
      const res = await apiFetch(`${API_BASE}/crm/agents/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: askQuery }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Ask failed");
      setAskResult(await res.json());
    } catch {
      setAskResult({ output: "Rio is temporarily unavailable.", errors: [] });
    } finally {
      setAskLoading(false);
    }
  }

  // Derived

  const docsByCollection = docs.reduce<Record<string, number>>((acc, d) => {
    acc[d.collection] = (acc[d.collection] ?? 0) + 1;
    return acc;
  }, {});

  const displayedDocs = filterCollection === "all"
    ? docs
    : docs.filter((d) => d.collection === filterCollection);

  // Render

  return (
    <div className="space-y-8 pb-10">
      {/* Header */}
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
          AI Memory
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
          <span className="gradient-text">Knowledge</span> Base
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          Ground Rio in your product facts, objection guides, and playbooks. Indexed documents
          are injected into every call and agent workflow automatically.
        </p>
      </div>

      {/* Collection stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {ALL_COLLECTIONS.map((col) => {
          const cfg = COLLECTION_CONFIG[col];
          const Icon = cfg.icon;
          return (
            <button
              key={col}
              onClick={() => setFilterCollection(filterCollection === col ? "all" : col)}
              className={`rounded-2xl border p-3 text-left transition hover:scale-105 ${
                filterCollection === col
                  ? colorClasses[cfg.color]
                  : "border-slate-200 bg-white/80 dark:border-white/10 dark:bg-slate-900/40"
              }`}
            >
              <Icon className="mb-1.5 h-5 w-5 opacity-70" />
              <p className="text-lg font-bold">{docsByCollection[col] ?? 0}</p>
              <p className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{cfg.label}</p>
            </button>
          );
        })}
      </div>

      {/* Semantic search */}
      <div className="rounded-2xl border border-slate-200 bg-white/80 p-5 dark:border-white/10 dark:bg-slate-900/40 space-y-4">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          <Search className="h-4 w-4 text-violet-500" />
          Semantic Search
        </h2>

        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search across your knowledge base..."
              className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-4 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            {searching && <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-violet-500" />}
          </div>
          <select
            value={searchCollection}
            onChange={(e) => setSearchCollection(e.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          >
            <option value="all">All collections</option>
            {ALL_COLLECTIONS.map((c) => (
              <option key={c} value={c}>{COLLECTION_CONFIG[c].label}</option>
            ))}
          </select>
        </div>

        {searchError && (
          <p className="text-sm text-red-500">{searchError}</p>
        )}

        {searchResults.length > 0 && (
          <div className="space-y-2">
            {searchResults.map((r, i) => (
              <div
                key={i}
                className="rounded-xl border border-slate-100 bg-slate-50 p-3.5 dark:border-white/5 dark:bg-slate-800/30"
              >
                <div className="flex items-start justify-between gap-4">
                  <p className="text-sm text-slate-800 dark:text-slate-200 flex-1">{r.text}</p>
                  <span className="shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-bold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                    {(r.score * 100).toFixed(0)}%
                  </span>
                </div>
                {r.metadata && Object.keys(r.metadata).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {Object.entries(r.metadata).slice(0, 4).map(([k, v]) => (
                      <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {!searching && searchQuery.trim() && searchResults.length === 0 && (
          <p className="text-sm text-slate-400">No results found for &ldquo;{searchQuery}&rdquo;.</p>
        )}
      </div>

      {/* Ask Rio */}
      <div className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-blue-50 p-5 dark:border-violet-500/20 dark:from-violet-500/5 dark:to-blue-500/5 space-y-4">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-violet-600 dark:text-violet-300">
          <Sparkles className="h-4 w-4" />
          Ask Rio
        </h2>
        <form onSubmit={handleAsk} className="flex gap-3">
          <input
            value={askQuery}
            onChange={(e) => setAskQuery(e.target.value)}
            placeholder="e.g. What are the top objections for enterprise clients?"
            className="flex-1 rounded-xl border border-violet-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-violet-400 dark:border-violet-500/30 dark:bg-slate-900/40"
          />
          <button
            type="submit"
            disabled={askLoading || !askQuery.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {askLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Ask
          </button>
        </form>
        {askResult && (
          <div className="rounded-xl border border-violet-200 bg-white p-4 dark:border-violet-500/20 dark:bg-slate-900/50 space-y-2">
            <p className="text-sm text-slate-800 dark:text-slate-200 whitespace-pre-wrap">{askResult.output}</p>
            {askResult.agents_run && askResult.agents_run.length > 0 && (
              <p className="text-xs text-slate-400">Agents used: {askResult.agents_run.join(", ")}</p>
            )}
          </div>
        )}
      </div>

      {/* RAG retrieval preview — what the agent will actually retrieve for a query */}
      <div className="rounded-2xl border border-blue-200 bg-blue-50/50 p-5 dark:border-blue-500/20 dark:bg-blue-500/5 space-y-4">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-blue-600 dark:text-blue-300">
            <Sparkles className="h-4 w-4" />
            RAG Retrieval Preview
          </h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Raw chunks the agent will see for a given query. No LLM — just the vector search.
            Filters by the &ldquo;{filterCollection}&rdquo; collection above.
          </p>
        </div>
        <form onSubmit={handleRagPreview} className="flex gap-3">
          <input
            value={ragQuery}
            onChange={(e) => setRagQuery(e.target.value)}
            placeholder="e.g. pricing tier for enterprise customers"
            className="flex-1 rounded-xl border border-blue-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-blue-500/30 dark:bg-slate-900/40"
          />
          <button
            type="submit"
            disabled={ragLoading || !ragQuery.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {ragLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Search
          </button>
        </form>
        {ragError && (
          <p className="text-xs font-medium text-amber-600 dark:text-amber-300">{ragError}</p>
        )}
        {ragResults.length > 0 && (
          <ol className="space-y-2">
            {ragResults.map((r, i) => (
              <li key={i} className="rounded-xl border border-blue-200 bg-white p-3 dark:border-blue-500/20 dark:bg-slate-900/50">
                <div className="mb-1.5 flex items-center gap-2 text-[10px] uppercase tracking-widest">
                  <span className="font-bold text-blue-600 dark:text-blue-300">#{i + 1}</span>
                  {r.collection && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 font-semibold text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
                      {r.collection}
                    </span>
                  )}
                  {typeof r.score === "number" && (
                    <span className="ml-auto font-mono text-slate-500">score {r.score.toFixed(3)}</span>
                  )}
                </div>
                <p className="text-xs text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{r.content}</p>
              </li>
            ))}
          </ol>
        )}
        {!ragLoading && ragQuery.trim() && ragResults.length === 0 && !ragError && (
          <p className="text-xs italic text-slate-500 dark:text-slate-400">
            No matches. Either the query is too narrow, the collection is empty, or RAG isn&rsquo;t configured.
          </p>
        )}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setFilterCollection("all")}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
              filterCollection === "all"
                ? "bg-violet-600 text-white shadow"
                : "bg-slate-100 text-slate-600 hover:bg-violet-100 hover:text-violet-700 dark:bg-slate-800 dark:text-slate-300"
            }`}
          >
            All
          </button>
          {ALL_COLLECTIONS.map((col) => (
            <button
              key={col}
              onClick={() => setFilterCollection(col === filterCollection ? "all" : col)}
              className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
                filterCollection === col
                  ? "bg-violet-600 text-white shadow"
                  : "bg-slate-100 text-slate-600 hover:bg-violet-100 hover:text-violet-700 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {COLLECTION_CONFIG[col].label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {reindexMsg && (
            <span className="text-xs text-violet-600 dark:text-violet-300">{reindexMsg}</span>
          )}
          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:border-violet-400 hover:text-violet-700 dark:border-white/10 dark:text-slate-300 transition disabled:opacity-50"
          >
            {reindexing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            Reindex all
          </button>
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20"
          >
            {showAdd ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {showAdd ? "Cancel" : "Add document"}
          </button>
        </div>
      </div>

      {/* Add document form */}
      {showAdd && (
        <form
          onSubmit={handleAdd}
          className="rounded-2xl border border-violet-200 bg-white/80 p-5 dark:border-violet-500/20 dark:bg-slate-900/40 space-y-4"
        >
          <h3 className="font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <FileText className="h-4 w-4 text-violet-500" />
            Add to knowledge base
          </h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-500">Collection</label>
              <select
                value={addForm.collection}
                onChange={(e) => setAddForm((f) => ({ ...f, collection: e.target.value }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              >
                {ALL_COLLECTIONS.map((c) => (
                  <option key={c} value={c}>{COLLECTION_CONFIG[c].label} — {COLLECTION_CONFIG[c].desc}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-500">Title</label>
              <input
                value={addForm.title}
                onChange={(e) => setAddForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="e.g. Enterprise Pricing Guide Q2"
                required
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-semibold text-slate-500">Content</label>
              <textarea
                value={addForm.content}
                onChange={(e) => setAddForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="Paste or type the full document content here. Rio will chunk, embed, and index it automatically."
                rows={6}
                required
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 font-mono"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-semibold text-slate-500">
                Tags <span className="font-normal text-slate-400">(comma-separated, optional)</span>
              </label>
              <input
                value={addForm.tags}
                onChange={(e) => setAddForm((f) => ({ ...f, tags: e.target.value }))}
                placeholder="e.g. enterprise, pricing, q2"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
          </div>
          {addError && <p className="text-sm text-red-500">{addError}</p>}
          <button
            type="submit"
            disabled={adding}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
          >
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {adding ? "Indexing..." : "Add & index document"}
          </button>
        </form>
      )}

      {/* Document list */}
      {docsLoading ? (
        <div className="flex items-center justify-center py-12 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading knowledge base...
        </div>
      ) : displayedDocs.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          <BookOpen className="mx-auto mb-3 h-8 w-8 opacity-40" />
          <p className="font-medium">No documents yet.</p>
          <p className="mt-1 text-sm">
            Add product specs, objection guides, playbooks, or competitor cards.
            Rio will use them on every call automatically.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {displayedDocs.map((doc) => {
            const isExpanded = expandedDoc === doc.id;
            return (
              <div
                key={doc.id}
                className={`rounded-2xl border bg-white/80 p-5 transition dark:bg-slate-900/40 ${
                  doc.is_active
                    ? "border-slate-200 dark:border-white/10"
                    : "border-slate-100 opacity-60 dark:border-white/5"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-900 dark:text-white truncate">
                        {doc.title}
                      </span>
                      <CollectionBadge collection={doc.collection} />
                      {!doc.is_active && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-400 dark:bg-slate-800">
                          Inactive
                        </span>
                      )}
                    </div>

                    {doc.tags && doc.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {doc.tags.map((tag) => (
                          <span
                            key={tag}
                            className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                          >
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}

                    <p className="text-xs text-slate-400">
                      {doc.last_indexed_at
                        ? `Indexed ${new Date(doc.last_indexed_at).toLocaleDateString()}`
                        : "Not yet indexed"}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      onClick={() => setExpandedDoc(isExpanded ? null : doc.id)}
                      className="inline-flex items-center gap-1 rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-500 hover:border-violet-400 hover:text-violet-700 dark:border-white/10 dark:text-slate-400 transition"
                    >
                      {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      {isExpanded ? "Hide" : "Preview"}
                    </button>
                    <button
                      onClick={() => handleDelete(doc.id)}
                      className="rounded-xl border border-red-200 p-1.5 text-red-500 hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 transition"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {isExpanded && (
                  <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50 p-4 dark:border-white/5 dark:bg-slate-800/30">
                    <pre className="whitespace-pre-wrap text-xs text-slate-700 dark:text-slate-300 font-mono leading-relaxed max-h-64 overflow-y-auto">
                      {doc.content}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
