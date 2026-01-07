"use client";

import { useEffect, useState } from "react";
import { Plus, Search, Phone, MoreHorizontal } from "lucide-react";

interface Lead {
    id: number;
    name: string;
    phone: string;
    status: string;
    notes: string;
}

export default function LeadsPage() {
    const [leads, setLeads] = useState<Lead[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetchLeads();
    }, []);

    const fetchLeads = async () => {
        try {
            // Use the correct port 6060
            const res = await fetch("http://localhost:6060/leads");
            if (res.ok) {
                const data = await res.json();
                setLeads(data);
            }
        } catch (err) {
            console.error("Failed to fetch leads", err);
        } finally {
            setLoading(false);
        }
    };

    const handleCall = async (phone: string, id: number) => {
        // Trigger outbound call via API
        try {
            await fetch(`http://localhost:6060/make-call?to=${phone}&lead_id=${id}`, { method: 'POST' });
            alert(`Calling ${phone}...`);
        } catch (e) {
            alert("Failed to initiate call");
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900">Lead Management</h1>
                    <p className="mt-1 text-slate-500">View and manage your potential customers.</p>
                </div>
                <button className="flex items-center space-x-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 transition-colors shadow-sm">
                    <Plus className="h-5 w-5" />
                    <span>Add Lead</span>
                </button>
            </div>

            <div className="flex items-center space-x-4 rounded-lg bg-white p-3 border border-slate-200 shadow-sm">
                <Search className="h-5 w-5 text-slate-400" />
                <input
                    type="text"
                    placeholder="Search leads..."
                    className="w-full bg-transparent text-slate-900 placeholder-slate-400 outline-none"
                />
            </div>

            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
                <table className="w-full text-left">
                    <thead className="bg-slate-50 text-slate-500 border-b border-slate-200">
                        <tr>
                            <th className="p-4 font-medium text-xs uppercase tracking-wider">Name</th>
                            <th className="p-4 font-medium text-xs uppercase tracking-wider">Phone</th>
                            <th className="p-4 font-medium text-xs uppercase tracking-wider">Status</th>
                            <th className="p-4 font-medium text-xs uppercase tracking-wider">Notes</th>
                            <th className="p-4 font-medium text-xs uppercase tracking-wider text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                        {loading ? (
                            <tr><td colSpan={5} className="p-8 text-center text-slate-500">Loading leads...</td></tr>
                        ) : leads.length === 0 ? (
                            <tr><td colSpan={5} className="p-8 text-center text-slate-500">No leads found.</td></tr>
                        ) : (
                            leads.map((lead) => (
                                <tr key={lead.id} className="hover:bg-slate-50 transition-colors">
                                    <td className="p-4 font-medium text-slate-900">{lead.name}</td>
                                    <td className="p-4 font-mono text-sm text-slate-500">{lead.phone}</td>
                                    <td className="p-4">
                                        <span className="inline-flex rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                                            {lead.status}
                                        </span>
                                    </td>
                                    <td className="p-4 text-slate-500 truncate max-w-xs">{lead.notes}</td>
                                    <td className="p-4 text-right">
                                        <div className="flex items-center justify-end space-x-2">
                                            <button
                                                onClick={() => handleCall(lead.phone, lead.id)}
                                                className="rounded p-2 text-green-600 hover:bg-green-50 hover:text-green-700 transition-colors"
                                                title="Call with AI"
                                            >
                                                <Phone className="h-4 w-4" />
                                            </button>
                                            <button className="rounded p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors">
                                                <MoreHorizontal className="h-4 w-4" />
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
    );
}
