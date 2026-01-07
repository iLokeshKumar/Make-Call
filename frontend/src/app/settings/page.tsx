"use client";

import { Save } from "lucide-react";

export default function SettingsPage() {
    return (
        <div className="space-y-6 max-w-2xl">
            <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900">Settings</h1>
                <p className="mt-1 text-slate-500">Manage your CRM preferences and integrations.</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
                <div className="p-6 space-y-6">

                    <div className="space-y-2">
                        <h3 className="text-lg font-medium text-slate-900">General</h3>
                        <div className="grid gap-4">
                            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-100 bg-slate-50">
                                <div>
                                    <p className="font-medium text-slate-700">Notifications</p>
                                    <p className="text-sm text-slate-500">Receive alerts for new leads</p>
                                </div>
                                <div className="h-6 w-11 rounded-full bg-blue-600"></div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-2">
                        <h3 className="text-lg font-medium text-slate-900">Integrations</h3>
                        <div className="grid gap-4">
                            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-100 bg-slate-50">
                                <div>
                                    <p className="font-medium text-slate-700">Twilio Status</p>
                                    <p className="text-sm text-slate-500">Voice & SMS Relay</p>
                                </div>
                                <span className="inline-flex items-center rounded-full bg-green-50 px-2 py-1 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-600/20">Connected</span>
                            </div>

                            <div className="flex items-center justify-between p-3 rounded-lg border border-slate-100 bg-slate-50">
                                <div>
                                    <p className="font-medium text-slate-700">Gemini AI</p>
                                    <p className="text-sm text-slate-500">Language Model</p>
                                </div>
                                <span className="inline-flex items-center rounded-full bg-green-50 px-2 py-1 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-600/20">Active</span>
                            </div>
                        </div>
                    </div>

                    <div className="pt-4">
                        <button className="flex items-center space-x-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 transition-colors">
                            <Save className="h-4 w-4" />
                            <span>Save Changes</span>
                        </button>
                    </div>

                </div>
            </div>
        </div>
    );
}
