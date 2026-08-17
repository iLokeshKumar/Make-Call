"use client";

import { useEffect, useState, useCallback } from "react";
import { Shield, Plus, Trash2, CheckCircle2, XCircle, Clock, FileText, Send, Check, AlertCircle, Loader2, PhoneCall } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE, CRM_BASE } from "@/lib/api";

type ComplianceApp = {
  id: number;
  application_type: string;
  status: string;
  provider: string;
  entity_name: string;
  entity_id?: string | null;
  header_id?: string | null;
  template_id?: string | null;
  document_urls?: Record<string, string> | null;
  notes?: string | null;
  created_at?: string | null;
};

export default function ComplianceTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [apps, setApps] = useState<ComplianceApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);

  // Form State
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    application_type: "dlt_140",
    provider: "twilio",
    entity_name: "",
    entity_id: "",
    header_id: "",
    template_id: "",
    notes: "",
  });

  // Truecaller State
  const [tcPhone, setTcPhone] = useState("");
  const [tcName, setTcName] = useState("");
  const [tcVerifying, setTcVerifying] = useState(false);
  const [tcResult, setTcResult] = useState<any>(null);
  const [tcError, setTcError] = useState<string | null>(null);

  // Document Submit State
  const [selectedAppForDocs, setSelectedAppForDocs] = useState<ComplianceApp | null>(null);
  const [docUrl, setDocUrl] = useState("");
  const [docName, setDocName] = useState("incorporation_certificate");

  const fetchApps = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${CRM_BASE}/compliance/applications`);
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) setApps(await res.json());
    } catch (e) {
      console.error("Failed to load compliance apps", e);
    } finally {
      setLoading(false);
    }
  }, [sessionTimeout]);

  useEffect(() => {
    fetchApps();
  }, [fetchApps]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.entity_name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        ...form,
        entity_id: form.entity_id ? form.entity_id : null,
        header_id: form.header_id ? form.header_id : null,
        template_id: form.template_id ? form.template_id : null,
        notes: form.notes ? form.notes : null,
      };
      const res = await apiFetch(`${CRM_BASE}/compliance/applications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to create application");
      }
      setShowModal(false);
      setForm({
        application_type: "dlt_140",
        provider: "twilio",
        entity_name: "",
        entity_id: "",
        header_id: "",
        template_id: "",
        notes: "",
      });
      fetchApps();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const submitDocuments = async (appId: number) => {
    if (!docUrl.trim()) return;
    setUpdatingId(appId);
    try {
      const res = await apiFetch(`${CRM_BASE}/compliance/applications/${appId}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_urls: { [docName]: docUrl.trim() }
        }),
      });
      if (res.ok) {
        setSelectedAppForDocs(null);
        setDocUrl("");
        fetchApps();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setUpdatingId(null);
    }
  };

  const updateStatus = async (appId: number, status: string, notes?: string) => {
    setUpdatingId(appId);
    try {
      const res = await apiFetch(`${CRM_BASE}/compliance/applications/${appId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, notes }),
      });
      if (res.ok) {
        fetchApps();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setUpdatingId(null);
    }
  };

  const handleTruecallerVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tcPhone.trim() || !tcName.trim()) return;
    setTcVerifying(true);
    setTcResult(null);
    setTcError(null);
    try {
      const res = await apiFetch(`${CRM_BASE}/compliance/truecaller/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: tcPhone.trim(), business_name: tcName.trim() }),
      });
      if (res.ok) {
        setTcResult(await res.json());
      } else {
        const body = await res.json().catch(() => ({}));
        setTcError(body.detail || "Truecaller verification service failed");
      }
    } catch (err) {
      setTcError("Network error during verification");
    } finally {
      setTcVerifying(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "approved":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 flex items-center gap-1"><Check className="h-3 w-3" /> Approved</span>;
      case "rejected":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300 flex items-center gap-1"><XCircle className="h-3 w-3" /> Rejected</span>;
      case "submitted":
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 flex items-center gap-1"><Send className="h-3 w-3" /> Submitted</span>;
      default:
        return <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 flex items-center gap-1"><Clock className="h-3 w-3" /> Draft</span>;
    }
  };

  const getTypeName = (type: string) => {
    switch (type) {
      case "dlt_140": return "140-series Telemarketing (India)";
      case "dlt_160": return "160-series Transactional (India)";
      case "truecaller_verification": return "Truecaller Brand Profile";
      default: return type;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-violet-500" />
        Loading compliance data...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* India DLT / Telephony Section */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-600">
              <Shield className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">DLT & Caller Registrations</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Manage Indian DLT Headers, templates and international compliance status</p>
            </div>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors"
          >
            <Plus className="h-4 w-4" /> Register Header/DLT
          </button>
        </div>

        {apps.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-8">No DLT or compliance registrations found. Click &ldquo;Register Header/DLT&rdquo; to begin.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {apps.map((app) => (
              <div key={app.id} className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/30 space-y-4 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="font-bold text-slate-800 dark:text-slate-200 text-sm">{app.entity_name}</h4>
                      <p className="text-xs text-slate-500 font-mono mt-0.5">{getTypeName(app.application_type)}</p>
                    </div>
                    {getStatusBadge(app.status)}
                  </div>

                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 pt-2 text-xs border-t border-slate-100 dark:border-slate-800">
                    <div>
                      <span className="text-slate-400">Provider:</span>
                      <span className="ml-1.5 font-medium text-slate-700 dark:text-slate-300 capitalize">{app.provider}</span>
                    </div>
                    {app.entity_id && (
                      <div>
                        <span className="text-slate-400">Entity ID:</span>
                        <span className="ml-1.5 font-mono text-slate-700 dark:text-slate-300">{app.entity_id}</span>
                      </div>
                    )}
                    {app.header_id && (
                      <div>
                        <span className="text-slate-400">Header ID:</span>
                        <span className="ml-1.5 font-mono text-slate-700 dark:text-slate-300">{app.header_id}</span>
                      </div>
                    )}
                    {app.template_id && (
                      <div>
                        <span className="text-slate-400">Template ID:</span>
                        <span className="ml-1.5 font-mono text-slate-700 dark:text-slate-300">{app.template_id}</span>
                      </div>
                    )}
                  </div>

                  {app.notes && (
                    <div className="bg-slate-50 dark:bg-slate-800/40 p-2.5 rounded text-xs text-slate-600 dark:text-slate-400 mt-2">
                      <span className="font-semibold block mb-0.5">Notes:</span>
                      {app.notes}
                    </div>
                  )}

                  {app.document_urls && Object.keys(app.document_urls).length > 0 && (
                    <div className="pt-2 text-xs">
                      <span className="text-slate-400">Attached Documents:</span>
                      <div className="flex flex-wrap gap-2 mt-1">
                        {Object.entries(app.document_urls).map(([name, url]) => (
                          <a key={name} href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 px-2 py-1 bg-violet-50 text-violet-600 dark:bg-violet-950/20 dark:text-violet-400 rounded hover:underline">
                            <FileText className="h-3 w-3" /> {name}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-3 pt-4 border-t border-slate-150 dark:border-slate-800/60 mt-auto">
                  {app.status === "draft" && (
                    <button
                      onClick={() => setSelectedAppForDocs(app)}
                      className="px-3 py-1.5 rounded bg-violet-100 hover:bg-violet-200 dark:bg-violet-900/30 dark:hover:bg-violet-900/50 text-violet-700 dark:text-violet-300 text-xs font-semibold"
                    >
                      Attach Documents & Submit
                    </button>
                  )}
                  {app.status === "submitted" && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => updateStatus(app.id, "approved")}
                        disabled={updatingId === app.id}
                        className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold disabled:opacity-50"
                      >
                        Approve (Verify)
                      </button>
                      <button
                        onClick={() => updateStatus(app.id, "rejected", "Documents not matching")}
                        disabled={updatingId === app.id}
                        className="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  )}
                  {updatingId === app.id && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Truecaller Brand Verification Section */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700">
            <PhoneCall className="h-5 w-5 text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Truecaller Verified Business Profile</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">Trigger active verification to display your green verified badge on customer devices</p>
          </div>
        </div>

        <form onSubmit={handleTruecallerVerify} className="max-w-xl grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Caller Phone Number</label>
            <input
              required
              value={tcPhone}
              onChange={e => setTcPhone(e.target.value)}
              placeholder="e.g. +919876543210"
              className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Registered Business Name</label>
            <input
              required
              value={tcName}
              onChange={e => setTcName(e.target.value)}
              placeholder="e.g. Acme Corporation"
              className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div className="md:col-span-2 flex justify-start pt-2">
            <button
              type="submit"
              disabled={tcVerifying || !tcPhone.trim() || !tcName.trim()}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50"
            >
              {tcVerifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <PhoneCall className="h-4 w-4" />}
              Submit to Truecaller Directory
            </button>
          </div>
        </form>

        {tcError && (
          <div className="text-sm text-rose-600 bg-rose-50 dark:bg-rose-950/30 rounded-lg p-3 max-w-xl flex items-center gap-2">
            <AlertCircle className="h-4 w-4" /> {tcError}
          </div>
        )}

        {tcResult && (
          <div className="max-w-xl p-4 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-800 dark:text-emerald-300 space-y-2">
            <div className="flex items-center gap-2 font-bold text-sm">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              Truecaller Profile Configured Successfully
            </div>
            <div className="text-xs space-y-1 mt-1 font-mono">
              <div><span className="text-slate-400">Caller ID:</span> {tcResult.display_name || tcName}</div>
              <div><span className="text-slate-400">Verification Status:</span> {tcResult.status || "VERIFIED"}</div>
              <div><span className="text-slate-400">Logo/Badge:</span> active (green verification bubble)</div>
            </div>
          </div>
        )}
      </div>

      {/* Modal - Document Submission */}
      {selectedAppForDocs && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-md w-full overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
              <h2 className="font-bold text-slate-900 dark:text-slate-100">Attach Compliance Files</h2>
              <button onClick={() => setSelectedAppForDocs(null)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Document Type</label>
                <select
                  value={docName}
                  onChange={e => setDocName(e.target.value)}
                  className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                >
                  <option value="incorporation_certificate">Certificate of Incorporation</option>
                  <option value="telecom_agreement">Telecom Service Agreement</option>
                  <option value="dlt_screenshot">DLT Portal Approved Screenshot</option>
                  <option value="brand_authorization">Brand Authorization Letter</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Document URL</label>
                <input
                  value={docUrl}
                  onChange={e => setDocUrl(e.target.value)}
                  placeholder="https://example.com/uploads/doc.pdf"
                  className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-850">
                <button
                  onClick={() => setSelectedAppForDocs(null)}
                  className="px-4 py-2 text-sm text-slate-500"
                >
                  Cancel
                </button>
                <button
                  onClick={() => submitDocuments(selectedAppForDocs.id)}
                  disabled={!docUrl.trim() || updatingId === selectedAppForDocs.id}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
                >
                  {updatingId === selectedAppForDocs.id ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit Application"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal - Create Application */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
              <h2 className="font-bold text-slate-900 dark:text-slate-100">Register Header / DLT Profile</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              {error && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 flex items-center gap-2"><AlertCircle className="h-4 w-4" />{error}</div>}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Application Type</label>
                  <select
                    value={form.application_type}
                    onChange={e => setForm(p => ({ ...p, application_type: e.target.value }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  >
                    <option value="dlt_140">140-series Telemarketing</option>
                    <option value="dlt_160">160-series Transactional</option>
                    <option value="truecaller_verification">Truecaller Business ID</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Telephony Provider</label>
                  <select
                    value={form.provider}
                    onChange={e => setForm(p => ({ ...p, provider: e.target.value }))}
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  >
                    <option value="twilio">Twilio</option>
                    <option value="plivo">Plivo</option>
                    <option value="exotel">Exotel</option>
                    <option value="vobiz">Vobiz</option>
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Entity Name (Legal Name)</label>
                  <input
                    required
                    value={form.entity_name}
                    onChange={e => setForm(p => ({ ...p, entity_name: e.target.value }))}
                    placeholder="Acme India Distribution Pvt. Ltd."
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Principal Entity ID (optional)</label>
                  <input
                    value={form.entity_id}
                    onChange={e => setForm(p => ({ ...p, entity_id: e.target.value }))}
                    placeholder="e.g. 1201159"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">DLT Header ID (optional)</label>
                  <input
                    value={form.header_id}
                    onChange={e => setForm(p => ({ ...p, header_id: e.target.value }))}
                    placeholder="e.g. ACMEIN"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Consent Template ID (optional)</label>
                  <input
                    value={form.template_id}
                    onChange={e => setForm(p => ({ ...p, template_id: e.target.value }))}
                    placeholder="e.g. 1402391280"
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Special Notes</label>
                  <textarea
                    value={form.notes}
                    onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
                    placeholder="Provide any extra details or DLT portal usernames if needed..."
                    className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none"
                    rows={3}
                  />
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
                  disabled={submitting || !form.entity_name.trim()}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save Profile"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
