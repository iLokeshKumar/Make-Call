"use client";

import {
  ChevronDown,
  ChevronRight,
  Download,
  FileSpreadsheet,
  Loader2,
  Plus,
  Search,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// ─── types ────────────────────────────────────────────────────────────────────

type ImportResult = {
  imported: number;
  skipped: number;
  errors?: string[];
  message?: string;
};

type Tab = "manual" | "file" | "apollo" | "lusha" | "zoominfo" | "linkedin" | "justdial" | "indiamart";

const TABS: { id: Tab; label: string; icon: React.ReactNode; badge?: string }[] = [
  { id: "manual",    label: "Manual",       icon: <Plus className="h-4 w-4" /> },
  { id: "file",      label: "CSV / Excel",  icon: <FileSpreadsheet className="h-4 w-4" /> },
  { id: "apollo",    label: "Apollo.io",    icon: <Search className="h-4 w-4" />, badge: "AI" },
  { id: "lusha",     label: "Lusha",        icon: <Users className="h-4 w-4" /> },
  { id: "zoominfo",  label: "ZoomInfo",     icon: <Search className="h-4 w-4" />, badge: "B2B" },
  { id: "linkedin",  label: "LinkedIn",     icon: <Upload className="h-4 w-4" /> },
  { id: "justdial",  label: "JustDial",     icon: <Upload className="h-4 w-4" /> },
  { id: "indiamart", label: "IndiaMart",    icon: <Upload className="h-4 w-4" /> },
];

// ─── helpers ──────────────────────────────────────────────────────────────────

function ResultBanner({ result, onDismiss }: { result: ImportResult; onDismiss: () => void }) {
  const ok = result.imported > 0;
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm flex items-start justify-between gap-3 ${
      ok ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
         : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
    }`}>
      <div>
        <p className="font-semibold">
          {result.imported} imported · {result.skipped} skipped
        </p>
        {result.message && <p className="mt-0.5 text-xs opacity-80">{result.message}</p>}
        {result.errors && result.errors.length > 0 && (
          <ul className="mt-1 list-disc list-inside text-xs opacity-70 space-y-0.5">
            {result.errors.slice(0, 5).map((e, i) => <li key={i}>{e}</li>)}
            {result.errors.length > 5 && <li>…and {result.errors.length - 5} more</li>}
          </ul>
        )}
      </div>
      <button onClick={onDismiss}><X className="h-4 w-4 opacity-60 hover:opacity-100" /></button>
    </div>
  );
}

// ─── tag input ────────────────────────────────────────────────────────────────

function TagInput({
  placeholder,
  tags,
  onChange,
}: {
  placeholder: string;
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim();
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setDraft("");
  }

  return (
    <div className="flex flex-wrap gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-slate-900/40 min-h-[42px]">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-lg bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-500/20 dark:text-violet-300">
          {t}
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))}>
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }}
        onBlur={add}
        placeholder={tags.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[120px] bg-transparent text-sm outline-none placeholder:text-slate-400"
      />
    </div>
  );
}

// ─── main modal ───────────────────────────────────────────────────────────────

export default function ImportLeadsModal({
  token,
  onClose,
  onImported,
}: {
  token: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const [tab, setTab] = useState<Tab>("manual");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  // manual
  const [manualForm, setManualForm] = useState({ name: "", normalized_phone: "", email: "", notes: "" });

  // file
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceTag, setSourceTag] = useState("csv_import");
  const [dragOver, setDragOver] = useState(false);

  // apollo
  const [apolloTitles, setApolloTitles] = useState<string[]>([]);
  const [apolloLocations, setApolloLocations] = useState<string[]>([]);
  const [apolloCompanies, setApolloCompanies] = useState<string[]>([]);
  const [apolloKeywords, setApolloKeywords] = useState("");
  const [apolloLimit, setApolloLimit] = useState(25);

  // lusha
  const [lushaRows, setLushaRows] = useState([{ first_name: "", last_name: "", company: "" }]);

  // zoominfo
  const [ziTitles, setZiTitles] = useState<string[]>([]);
  const [ziLocations, setZiLocations] = useState<string[]>([]);
  const [ziCompanies, setZiCompanies] = useState<string[]>([]);
  const [ziDepartments, setZiDepartments] = useState<string[]>([]);
  const [ziKeywords, setZiKeywords] = useState("");
  const [ziLimit, setZiLimit] = useState(25);

  async function post(url: string, body?: object) {
    const res = await fetch(`${API_BASE}${url}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    return data as ImportResult;
  }

  async function handleManual(e: React.FormEvent) {
    e.preventDefault();
    if (!manualForm.name || !manualForm.normalized_phone) return;
    setBusy(true); setResult(null);
    try {
      await fetch(`${API_BASE}/crm/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(manualForm),
      }).then(async (r) => {
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail); }
        return r.json();
      });
      setResult({ imported: 1, skipped: 0 });
      setManualForm({ name: "", normalized_phone: "", email: "", notes: "" });
      onImported();
    } catch (err) {
      setResult({ imported: 0, skipped: 1, errors: [String(err)] });
    } finally { setBusy(false); }
  }

  async function handleFile(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("source_tag", sourceTag);
      const res = await fetch(`${API_BASE}/crm/leads/import/file`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setResult(data);
      setFile(null);
      onImported();
    } catch (err) {
      setResult({ imported: 0, skipped: 0, errors: [String(err)] });
    } finally { setBusy(false); }
  }

  async function handleApollo(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setResult(null);
    try {
      const data = await post("/crm/leads/import/apollo", {
        job_titles: apolloTitles,
        locations: apolloLocations,
        companies: apolloCompanies,
        keywords: apolloKeywords,
        limit: apolloLimit,
      });
      setResult(data);
      onImported();
    } catch (err) {
      setResult({ imported: 0, skipped: 0, errors: [String(err)] });
    } finally { setBusy(false); }
  }

  async function handleZoomInfo(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setResult(null);
    try {
      const data = await post("/crm/leads/import/zoominfo", {
        job_titles: ziTitles,
        locations: ziLocations,
        companies: ziCompanies,
        departments: ziDepartments,
        keywords: ziKeywords,
        limit: ziLimit,
      });
      setResult(data);
      onImported();
    } catch (err) {
      setResult({ imported: 0, skipped: 0, errors: [String(err)] });
    } finally { setBusy(false); }
  }

  async function handleLusha(e: React.FormEvent) {
    e.preventDefault();
    const queries = lushaRows.filter((r) => r.first_name.trim());
    if (!queries.length) return;
    setBusy(true); setResult(null);
    try {
      const data = await post("/crm/leads/import/lusha", { queries });
      setResult(data);
      onImported();
    } catch (err) {
      setResult({ imported: 0, skipped: 0, errors: [String(err)] });
    } finally { setBusy(false); }
  }

  function handleFileDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }

  const inputCls = "w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl dark:bg-slate-900 flex flex-col max-h-[90vh]">
        {/* header */}
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">Import Leads</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">Manual · CSV/Excel · Apollo · Lusha · LinkedIn · JustDial · IndiaMart</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-white/10">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* tabs */}
        <div className="flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-white/10 px-4 pt-3">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setResult(null); }}
              className={`flex items-center gap-1.5 whitespace-nowrap rounded-t-lg px-3 py-2 text-xs font-semibold transition ${
                tab === t.id
                  ? "border-b-2 border-violet-600 text-violet-700 dark:text-violet-300"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              {t.icon}
              {t.label}
              {t.badge && (
                <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-700 dark:bg-violet-500/20 dark:text-violet-300">
                  {t.badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {result && <ResultBanner result={result} onDismiss={() => setResult(null)} />}

          {/* ── MANUAL ── */}
          {tab === "manual" && (
            <form onSubmit={handleManual} className="space-y-3">
              <input required value={manualForm.name} onChange={(e) => setManualForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Full name *" className={inputCls} />
              <input required value={manualForm.normalized_phone} onChange={(e) => setManualForm((f) => ({ ...f, normalized_phone: e.target.value }))}
                placeholder="Phone number * (e.g. +919876543210)" className={inputCls} />
              <input value={manualForm.email} onChange={(e) => setManualForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="Email (optional)" className={inputCls} />
              <textarea value={manualForm.notes} onChange={(e) => setManualForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Notes (optional)" rows={3} className={inputCls} />
              <SubmitBtn busy={busy} label="Add Lead" />
            </form>
          )}

          {/* ── FILE UPLOAD ── */}
          {tab === "file" && (
            <form onSubmit={handleFile} className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  Upload a <strong>CSV or Excel</strong> file. Auto-detects LinkedIn, JustDial, IndiaMart and standard formats.
                </p>
                <a
                  href={`${API_BASE}/crm/leads/import/template`}
                  download
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-violet-300 hover:text-violet-700 dark:border-white/10 dark:text-slate-300"
                >
                  <Download className="h-3.5 w-3.5" /> Template
                </a>
              </div>

              {/* drag-drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleFileDrop}
                onClick={() => fileRef.current?.click()}
                className={`cursor-pointer rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
                  dragOver ? "border-violet-400 bg-violet-50 dark:bg-violet-500/10" : "border-slate-300 hover:border-violet-300 dark:border-white/20"
                }`}
              >
                <FileSpreadsheet className="mx-auto h-10 w-10 text-slate-400 mb-3" />
                {file ? (
                  <p className="font-medium text-slate-700 dark:text-slate-200">{file.name} <span className="text-xs text-slate-400">({(file.size / 1024).toFixed(0)} KB)</span></p>
                ) : (
                  <>
                    <p className="font-medium text-slate-600 dark:text-slate-300">Drop file here or click to browse</p>
                    <p className="text-xs text-slate-400 mt-1">.csv, .xlsx, .xls — max 5 MB</p>
                  </>
                )}
                <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Source label</label>
                <select value={sourceTag} onChange={(e) => setSourceTag(e.target.value)} className={inputCls}>
                  <option value="csv_import">CSV Import</option>
                  <option value="linkedin">LinkedIn</option>
                  <option value="justdial">JustDial</option>
                  <option value="indiamart">IndiaMart</option>
                  <option value="sulekha">Sulekha</option>
                  <option value="tradeindia">TradeIndia</option>
                  <option value="website">Website</option>
                  <option value="referral">Referral</option>
                  <option value="event">Event</option>
                </select>
              </div>

              <SubmitBtn busy={busy} label="Import File" disabled={!file} />
            </form>
          )}

          {/* ── APOLLO ── */}
          {tab === "apollo" && (
            <form onSubmit={handleApollo} className="space-y-4">
              <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-xs text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300">
                Searches Apollo.io B2B database. Requires <strong>Apollo API key</strong> in Settings → Integrations.
                Press <kbd className="rounded bg-blue-100 px-1 font-mono dark:bg-blue-500/20">Enter</kbd> or comma to add each tag.
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Job titles</label>
                <TagInput placeholder='e.g. "VP Sales", "Head of Marketing"' tags={apolloTitles} onChange={setApolloTitles} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Locations</label>
                <TagInput placeholder='e.g. "Mumbai", "Bangalore", "India"' tags={apolloLocations} onChange={setApolloLocations} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Companies</label>
                <TagInput placeholder='e.g. "Reliance Industries"' tags={apolloCompanies} onChange={setApolloCompanies} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Keywords</label>
                <input value={apolloKeywords} onChange={(e) => setApolloKeywords(e.target.value)}
                  placeholder='e.g. "SaaS sales CRM"' className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Max results</label>
                <select value={apolloLimit} onChange={(e) => setApolloLimit(Number(e.target.value))} className={inputCls}>
                  {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n} contacts</option>)}
                </select>
              </div>
              <SubmitBtn busy={busy} label="Search & Import" />
            </form>
          )}

          {/* ── LUSHA ── */}
          {tab === "lusha" && (
            <form onSubmit={handleLusha} className="space-y-4">
              <div className="rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 text-xs text-purple-700 dark:border-purple-500/20 dark:bg-purple-500/10 dark:text-purple-300">
                Lookups contacts from Lusha's B2B database. Requires <strong>Lusha API key</strong> in Settings → Integrations.
              </div>

              <div className="space-y-2">
                {lushaRows.map((row, i) => (
                  <div key={i} className="grid grid-cols-3 gap-2">
                    <input value={row.first_name} onChange={(e) => setLushaRows((rs) => rs.map((r, j) => j === i ? { ...r, first_name: e.target.value } : r))}
                      placeholder="First name *" className={inputCls} />
                    <input value={row.last_name} onChange={(e) => setLushaRows((rs) => rs.map((r, j) => j === i ? { ...r, last_name: e.target.value } : r))}
                      placeholder="Last name" className={inputCls} />
                    <div className="flex gap-1">
                      <input value={row.company} onChange={(e) => setLushaRows((rs) => rs.map((r, j) => j === i ? { ...r, company: e.target.value } : r))}
                        placeholder="Company" className={inputCls} />
                      {lushaRows.length > 1 && (
                        <button type="button" onClick={() => setLushaRows((rs) => rs.filter((_, j) => j !== i))}
                          className="rounded-lg border border-slate-200 px-2 text-slate-400 hover:text-red-500 dark:border-white/10">
                          <X className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <button type="button" onClick={() => setLushaRows((rs) => [...rs, { first_name: "", last_name: "", company: "" }])}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-600 hover:underline dark:text-violet-400">
                <Plus className="h-3.5 w-3.5" /> Add another person
              </button>

              <SubmitBtn busy={busy} label="Lookup & Import" />
            </form>
          )}

          {/* ── ZOOMINFO ── */}
          {tab === "zoominfo" && (
            <form onSubmit={handleZoomInfo} className="space-y-4">
              <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-xs text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300">
                Searches ZoomInfo B2B contact database. Requires <strong>ZOOMINFO_CLIENT_ID</strong> and <strong>ZOOMINFO_API_KEY</strong> in Settings → Integrations.
                Press <kbd className="rounded bg-sky-100 px-1 font-mono dark:bg-sky-500/20">Enter</kbd> or comma to add each tag.
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Job titles</label>
                <TagInput placeholder='e.g. "CTO", "VP of Engineering"' tags={ziTitles} onChange={setZiTitles} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Departments</label>
                <TagInput placeholder='e.g. "Sales", "Finance", "IT"' tags={ziDepartments} onChange={setZiDepartments} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Locations</label>
                <TagInput placeholder='e.g. "Mumbai", "Delhi NCR"' tags={ziLocations} onChange={setZiLocations} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Companies</label>
                <TagInput placeholder='e.g. "Infosys", "TCS"' tags={ziCompanies} onChange={setZiCompanies} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Keywords</label>
                <input value={ziKeywords} onChange={(e) => setZiKeywords(e.target.value)}
                  placeholder='e.g. "cloud ERP procurement"' className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Max results</label>
                <select value={ziLimit} onChange={(e) => setZiLimit(Number(e.target.value))} className={inputCls}>
                  {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n} contacts</option>)}
                </select>
              </div>
              <SubmitBtn busy={busy} label="Search & Import" />
            </form>
          )}

          {/* ── LINKEDIN ── */}
          {tab === "linkedin" && (
            <CsvGuideTab
              source="LinkedIn"
              steps={[
                "Go to Sales Navigator or LinkedIn Connections",
                "Click ⋯ → Export connections → Request archive",
                "Download the CSV from your email",
                "Upload below — we map First Name, Last Name, Company, Title automatically",
              ]}
              onFileSelected={(f) => { setFile(f); setSourceTag("linkedin"); setTab("file"); }}
            />
          )}

          {/* ── JUSTDIAL ── */}
          {tab === "justdial" && (
            <CsvGuideTab
              source="JustDial"
              steps={[
                "Log into JustDial Lead Manager (business.justdial.com)",
                "Go to Leads → Download leads as CSV/Excel",
                "Upload below — we map Company Name, Contact Person, Mobile, Email, City",
              ]}
              onFileSelected={(f) => { setFile(f); setSourceTag("justdial"); setTab("file"); }}
            />
          )}

          {/* ── INDIAMART ── */}
          {tab === "indiamart" && (
            <CsvGuideTab
              source="IndiaMart"
              steps={[
                "Log into IndiaMart Seller Panel (seller.indiamart.com)",
                "Go to Leads Manager → All Leads → Export to Excel",
                "Upload below — we map Contact Name, Mobile, Email, Company Name, City",
              ]}
              onFileSelected={(f) => { setFile(f); setSourceTag("indiamart"); setTab("file"); }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─── sub-components ───────────────────────────────────────────────────────────

function SubmitBtn({ busy, label, disabled }: { busy: boolean; label: string; disabled?: boolean }) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01] disabled:opacity-60"
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {label}
    </button>
  );
}

function CsvGuideTab({
  source,
  steps,
  onFileSelected,
}: {
  source: string;
  steps: string[];
  onFileSelected: (file: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-5">
      <ol className="space-y-2.5">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3 text-sm text-slate-700 dark:text-slate-300">
            <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-violet-100 text-xs font-bold text-violet-700 dark:bg-violet-500/20 dark:text-violet-300">
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>

      <div
        onClick={() => ref.current?.click()}
        className="cursor-pointer rounded-2xl border-2 border-dashed border-slate-300 px-6 py-8 text-center hover:border-violet-300 dark:border-white/20"
      >
        <Upload className="mx-auto h-8 w-8 text-slate-400 mb-2" />
        <p className="font-medium text-slate-600 dark:text-slate-300">Upload {source} export</p>
        <p className="text-xs text-slate-400 mt-1">.csv or .xlsx</p>
        <input ref={ref} type="file" accept=".csv,.xlsx,.xls" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) onFileSelected(f); }} />
      </div>
    </div>
  );
}
