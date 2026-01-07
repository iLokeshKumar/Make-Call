"use client";

import { Phone } from "lucide-react";

export default function CallsPage() {
    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900">Call History</h1>
                <p className="mt-1 text-slate-500">Recent voice interactions with the AI agent.</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
                <div className="p-12 text-center text-slate-500">
                    <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-slate-50">
                        <Phone className="h-8 w-8 text-slate-300" />
                    </div>
                    <h3 className="text-lg font-medium text-slate-900">No calls recorded yet</h3>
                    <p className="mt-1 text-sm text-slate-500">Initiate a call from the Leads page to see history here.</p>
                </div>
            </div>
        </div>
    );
}
