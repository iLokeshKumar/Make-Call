"use client";

import { useRef, useState } from "react";
import { Download, FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { CRM_BASE } from "@/lib/api";

type ImportResult = {
  total_rows: number;
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; name: string; error: string }[];
};

export default function ImportProductsModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [sheetName, setSheetName] = useState("");
  const [sheetsLoading, setSheetsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function isExcel(f: File) {
    return /\.(xlsx|xls)$/i.test(f.name);
  }

  async function pickFile(f: File) {
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["csv", "xlsx", "xls"].includes(ext)) {
      setError("Only CSV and Excel (.xlsx / .xls) files are supported.");
      return;
    }
    setFile(f);
    setSheets([]);
    setSheetName("");
    setResult(null);
    setError(null);

    if (isExcel(f)) {
      setSheetsLoading(true);
      try {
        const fd = new FormData();
        fd.append("file", f);
        const res = await apiFetch(`${CRM_BASE}/products/import/sheets`, { method: "POST", body: fd });
        if (res.ok) {
          const data = await res.json();
          setSheets(data.sheets ?? []);
          if (data.sheets?.length > 0) setSheetName(data.sheets[0]);
        }
      } catch {
        // non-fatal — user can still import without sheet selection
      } finally {
        setSheetsLoading(false);
      }
    }
  }

  async function handleImport() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (sheetName) fd.append("sheet_name", sheetName);
      const res = await apiFetch(`${CRM_BASE}/products/import`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join("; ")
          : (data.detail ?? `Server error ${res.status}`);
        setError(detail);
      } else {
        setResult(data as ImportResult);
        onDone();
      }
    } catch {
      setError("Network error — could not reach server.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadTemplate() {
    const res = await apiFetch(`${CRM_BASE}/products/import/template`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "products_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-2xl w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-violet-600" />
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Import Products</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Template download */}
          <button
            onClick={downloadTemplate}
            className="flex items-center gap-2 text-sm text-violet-600 dark:text-violet-400 hover:underline"
          >
            <Download className="h-4 w-4" />
            Download CSV template
          </button>

          {/* Drop zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) pickFile(f); }}
            onClick={() => fileRef.current?.click()}
            className={`relative flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed cursor-pointer py-10 transition-colors ${
              dragging
                ? "border-violet-500 bg-violet-50 dark:bg-violet-900/20"
                : "border-slate-200 dark:border-slate-700 hover:border-violet-400 hover:bg-slate-50 dark:hover:bg-slate-800/40"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) pickFile(f); }}
            />
            <Upload className="h-8 w-8 text-slate-300 dark:text-slate-600" />
            {file ? (
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{file.name}</p>
            ) : (
              <>
                <p className="text-sm text-slate-500">Drag & drop a CSV or Excel file, or click to browse</p>
                <p className="text-xs text-slate-400">CSV · XLSX · XLS · max 10 MB</p>
              </>
            )}
          </div>

          {/* Sheet selector for Excel files */}
          {file && isExcel(file) && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Sheet to import
              </label>
              {sheetsLoading ? (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Detecting sheets…
                </div>
              ) : sheets.length > 1 ? (
                <select
                  value={sheetName}
                  onChange={e => setSheetName(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                >
                  {sheets.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              ) : sheets.length === 1 ? (
                <p className="text-xs text-slate-500">Sheet: <span className="font-medium">{sheets[0]}</span></p>
              ) : null}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 px-4 py-2.5 text-sm text-rose-700 dark:text-rose-300">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-800 px-4 py-3 space-y-1">
              <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
                Import complete — {result.total_rows} rows processed
              </p>
              <p className="text-xs text-emerald-700 dark:text-emerald-400">
                {result.created} created · {result.updated} updated · {result.skipped} skipped
              </p>
              {result.errors.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  {result.errors.slice(0, 5).map((e, i) => (
                    <p key={i} className="text-xs text-rose-600 dark:text-rose-400">
                      Row {e.row}: {e.name} — {e.error}
                    </p>
                  ))}
                  {result.errors.length > 5 && (
                    <p className="text-xs text-slate-400">…and {result.errors.length - 5} more errors</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-100 dark:border-slate-800">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={handleImport}
              disabled={!file || loading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              Import
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
