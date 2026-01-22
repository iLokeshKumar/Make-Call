"use client";

import { useEffect, useState } from "react";
import { Upload, FileSpreadsheet, CheckCircle, AlertCircle, X, Phone, Trash2, Search, Sparkles } from "lucide-react";

interface Lead {
    id: number;
    name: string;
    phone: string;
    email?: string;
    status: string;
    source: string;
    notes?: string;
    enrichment_status?: string;
}

export default function LeadsPage() {
    const [leads, setLeads] = useState<Lead[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [uploadResult, setUploadResult] = useState<{ message: string; errors: string[] } | null>(null);
    const [searchQuery, setSearchQuery] = useState("");

    const API_BASE = "http://localhost:6060";

    const fetchLeads = async () => {
        try {
            const res = await fetch(`${API_BASE}/leads`);
            const data = await res.json();
            setLeads(data);
        } catch (error) {
            console.error("Error fetching leads:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchLeads();
    }, []);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            setFile(e.target.files[0]);
            setUploadResult(null);
        }
    };

    const handleUpload = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!file) return;

        setUploading(true);
        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch(`${API_BASE}/leads/upload`, {
                method: "POST",
                body: formData,
            });
            const data = await res.json();

            if (res.ok) {
                setUploadResult({ message: data.message, errors: data.errors || [] });
                fetchLeads();
                setFile(null);
            } else {
                setUploadResult({ message: data.detail || "Upload failed", errors: [] });
            }
        } catch (error) {
            console.error("Error uploading file:", error);
            setUploadResult({ message: "Network error during upload", errors: [] });
        } finally {
            setUploading(false);
        }
    };

    const handleCall = async (phone: string, id: number) => {
        try {
            await fetch(`${API_BASE}/make-call?to=${encodeURIComponent(phone)}&lead_id=${id}`, { method: 'POST' });
            alert(`Initiating call to ${phone}...`);
        } catch (e) {
            alert("Failed to initiate call");
        }
    };

    // Keep existing delete functionality
    const handleDeleteLead = async (id: number) => {
        if (!confirm("Are you sure you want to delete this lead?")) return;
        try {
            const res = await fetch(`${API_BASE}/leads/${id}`, { method: "DELETE" });

        } catch (error) {
            console.error("Error deleting lead:", error);
        }
    };

    const filteredLeads = leads.filter(lead =>
        lead.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        lead.phone?.includes(searchQuery)
    );

    return (
        <div className="space-y-6 pb-8">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-4xl font-bold tracking-tight">
                        <span className="gradient-text">Lead Management</span>
                    </h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
                        Import and manage your sales leads.
                    </p>
                </div>
            </div>

            {/* Upload Section */}
            <div className="rounded-2xl glass p-8 border border-white/40 dark:border-white/10 shadow-xl">
                <div className="flex flex-col md:flex-row items-center gap-8">
                    <div className="flex-1 space-y-4">
                        <div className="flex items-center space-x-3">
                            <div className="p-3 rounded-xl bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
                                <FileSpreadsheet className="h-8 w-8" />
                            </div>
                            <h2 className="text-xl font-bold text-slate-900 dark:text-white">Import Leads (Excel/CSV)</h2>
                        </div>
                        <p className="text-slate-600 dark:text-slate-400 text-sm leading-relaxed">
                            Upload a <strong>.xlsx</strong> or <strong>.csv</strong> file to bulk import leads.
                            <br />Ensure columns include: <code>Name</code>, <code>Phone</code>. Optional: <code>Email</code>, <code>Notes</code>.
                        </p>
                    </div>

                    <div className="flex-1 w-full max-w-md">
                        <form onSubmit={handleUpload} className="space-y-4">
                            <div className="relative group">
                                <input
                                    type="file"
                                    accept=".csv, .xlsx, .xls"
                                    onChange={handleFileChange}
                                    className="block w-full text-sm text-slate-500
                                    file:mr-4 file:py-2.5 file:px-4
                                    file:rounded-xl file:border-0
                                    file:text-sm file:font-semibold
                                    file:bg-violet-50 file:text-violet-700
                                    hover:file:bg-violet-100
                                    cursor-pointer border border-dashed border-slate-300 rounded-xl p-2
                                    "
                                />
                            </div>

                            {file && (
                                <button
                                    type="submit"
                                    disabled={uploading}
                                    className="w-full flex items-center justify-center space-x-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 font-semibold text-white shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {uploading ? (
                                        <span className="animate-pulse">Uploading...</span>
                                    ) : (
                                        <>
                                            <Upload className="h-5 w-5" />
                                            <span>Start Import</span>
                                        </>
                                    )}
                                </button>
                            )}
                        </form>
                    </div>
                </div>

                {uploadResult && (
                    <div className={`mt-6 p-4 rounded-xl flex items-start space-x-3 ${uploadResult.errors.length > 0 ? 'bg-yellow-50 text-yellow-800' : 'bg-green-50 text-green-800'}`}>
                        {uploadResult.errors.length > 0 ? <AlertCircle className="h-5 w-5 mt-0.5" /> : <CheckCircle className="h-5 w-5 mt-0.5" />}
                        <div>
                            <p className="font-bold">{uploadResult.message}</p>
                            {uploadResult.errors.length > 0 && (
                                <ul className="mt-2 text-sm list-disc list-inside space-y-1">
                                    {uploadResult.errors.map((err, i) => (
                                        <li key={i}>{err}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Apollo Section */}
            <div className="rounded-2xl glass p-8 border border-white/40 dark:border-white/10 shadow-xl relative overflow-hidden mb-8">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                    <Search className="w-32 h-32" />
                </div>
                <div className="flex flex-col md:flex-row items-center gap-8 relative z-10">
                    <div className="flex-1 space-y-4">
                        <div className="flex items-center space-x-3">
                            <div className="p-3 rounded-xl bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
                                <Search className="h-8 w-8" />
                            </div>
                            <h2 className="text-xl font-bold text-slate-900 dark:text-white">Automated Feed (Apollo.io)</h2>
                        </div>
                        <p className="text-slate-600 dark:text-slate-400 text-sm leading-relaxed">
                            Connect to <strong>Apollo.io</strong> to verify and fetch potential leads automatically.
                            <br />Enter target keywords (e.g., "Software Companies", "Hospitals") to populate your queue.
                        </p>
                    </div>

                    <div className="flex-1 w-full max-w-md">
                        <div className="space-y-4">
                            <input
                                type="text"
                                placeholder="Target Industry or Keywords..."
                                className="block w-full rounded-xl border-slate-300 p-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                id="apollo-search"
                            />
                            <button
                                onClick={async () => {
                                    const input = document.getElementById('apollo-search') as HTMLInputElement;
                                    const keywords = input.value || "Technology";
                                    const btn = document.getElementById('apollo-btn') as HTMLButtonElement;

                                    if (btn) {
                                        btn.disabled = true;
                                        btn.innerText = "Fetching...";
                                    }

                                    try {
                                        const res = await fetch(`${API_BASE}/leads/fetch-apollo`, {
                                            method: 'POST',
                                            headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({ keywords })
                                        });
                                        const data = await res.json();
                                        if (res.ok) {
                                            alert(data.message);
                                            fetchLeads();
                                        } else {
                                            alert("Error: " + data.detail);
                                        }
                                    } catch (e) {
                                        alert("Connection Error");
                                    } finally {
                                        if (btn) {
                                            btn.disabled = false;
                                            btn.innerText = "Fetch from Apollo";
                                        }
                                    }
                                }}
                                id="apollo-btn"
                                className="w-full flex items-center justify-center space-x-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-600 px-4 py-3 font-semibold text-white shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all disabled:opacity-50"
                            >
                                <Search className="h-5 w-5" />
                                <span>Fetch from Apollo</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Leads Table */}
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
                <div className="px-6 py-4 border-b border-white/20 dark:border-white/10 bg-white/40 dark:bg-slate-800/40 flex justify-between items-center">
                    <h3 className="font-bold text-lg text-slate-800 dark:text-slate-200">Lead Queue</h3>
                    <div className="relative w-64">
                        <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
                            <Search className="h-4 w-4 text-slate-400" />
                        </div>
                        <input
                            type="text"
                            placeholder="Search..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full rounded-lg bg-white/50 border border-slate-200 pl-9 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                        />
                    </div>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="border-b border-white/20 dark:border-white/10 bg-white/40 dark:bg-slate-800/40">
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Source</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Name</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Phone</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Status</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300 text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/10 dark:divide-white/5">
                            {loading ? (
                                <tr><td colSpan={5} className="px-6 py-12 text-center text-slate-500">Loading leads...</td></tr>
                            ) : filteredLeads.length === 0 ? (
                                <tr><td colSpan={5} className="px-6 py-12 text-center text-slate-500">No leads found. Upload a file above.</td></tr>
                            ) : (
                                filteredLeads.map((lead) => (
                                    <tr key={lead.id} className="hover:bg-white/40 dark:hover:bg-slate-800/40 transition-colors">
                                        <td className="px-6 py-4">
                                            <span className="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 ring-1 ring-inset ring-slate-500/10">
                                                {lead.source || "Manual"}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 font-bold text-slate-900 dark:text-slate-100">
                                            {lead.name}
                                        </td>
                                        <td className="px-6 py-4 font-mono text-slate-600 dark:text-slate-400">
                                            {lead.phone}
                                        </td>
                                        <td className="px-6 py-4">
                                            <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${lead.status === 'New'
                                                ? 'bg-blue-50 text-blue-700 ring-blue-600/20'
                                                : 'bg-green-50 text-green-700 ring-green-600/20'
                                                }`}>
                                                {lead.status}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-right">
                                            <div className="flex justify-end items-center space-x-2">
                                                <button
                                                    onClick={async () => {
                                                        try {
                                                            const res = await fetch(`${API_BASE}/leads/${lead.id}/enrich`, { method: 'POST' });
                                                            if (res.ok) {
                                                                alert("Successfully Enriched");
                                                                fetchLeads();
                                                            } else {
                                                                alert("Enrichment failed");
                                                            }
                                                        } catch (e) {
                                                            alert("Link Error");
                                                        }
                                                    }}
                                                    title={lead.enrichment_status || "Not Enriched"}
                                                    className={`inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-sm font-semibold transition-all ${lead.enrichment_status && lead.enrichment_status !== 'Not Enriched'
                                                            ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                                                            : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                                                        }`}
                                                >
                                                    <Sparkles className="h-3 w-3" />
                                                    <span>Enrich</span>
                                                </button>

                                                <button
                                                    onClick={() => handleCall(lead.phone, lead.id)}
                                                    className="inline-flex items-center space-x-1 bg-violet-100 hover:bg-violet-200 text-violet-700 px-3 py-1.5 rounded-lg text-sm font-semibold transition-colors"
                                                >
                                                    <Phone className="h-3 w-3" />
                                                    <span>Call</span>
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
