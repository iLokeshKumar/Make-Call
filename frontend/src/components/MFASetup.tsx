"use client";

import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Shield, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

export default function MFASetup() {
    const { user, token, refreshUser } = useAuth();
    const [setupData, setSetupData] = useState<{ secret: string; qr_code: string } | null>(null);
    const [mfaCode, setMfaCode] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState(false);
    const [loading, setLoading] = useState(false);

    const startSetup = async () => {
        setLoading(true);
        setError("");
        try {
            const res = await fetch("http://localhost:6060/auth/mfa/setup", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                const data = await res.json();
                setSetupData(data);
            } else {
                const err = await res.json();
                setError(err.detail || "Failed to start MFA setup");
            }
        } catch (err) {
            setError("Network error");
        } finally {
            setLoading(false);
        }
    };

    const verifyMFA = async () => {
        setLoading(true);
        setError("");
        try {
            const res = await fetch("http://localhost:6060/auth/mfa/enable", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ token: mfaCode }),
            });
            if (res.ok) {
                setSuccess(true);
                await refreshUser(); // Refresh user context to show MFA as enabled
            } else {
                const err = await res.json();
                setError(err.detail || "Invalid code");
            }
        } catch (err) {
            setError("Network error");
        } finally {
            setLoading(false);
        }
    };

    if (user?.mfa_enabled) {
        return (
            <div className="flex items-center space-x-2 text-green-600 dark:text-green-400 font-bold p-4 bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-200 dark:border-green-800">
                <CheckCircle2 className="h-5 w-5" />
                <span>Two-Factor Authentication is Enabled</span>
            </div>
        );
    }

    if (success) {
        return (
            <div className="flex flex-col items-center space-y-4 p-8 bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-200 dark:border-green-800 text-center">
                <CheckCircle2 className="h-12 w-12 text-green-500" />
                <h3 className="text-xl font-bold">MFA Enabled!</h3>
                <p className="text-sm text-slate-600 dark:text-slate-400">Your account is now protected with 2FA.</p>
            </div>
        );
    }

    return (
        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 mt-6">
            <div className="flex items-center space-x-3 mb-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-md">
                    <Shield className="h-5 w-5 text-white" />
                </div>
                <div>
                    <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Security</h3>
                    <p className="text-sm text-slate-500 dark:text-slate-400">Add an extra layer of protection</p>
                </div>
            </div>

            {!setupData ? (
                <button
                    onClick={startSetup}
                    disabled={loading}
                    className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold transition-all disabled:opacity-50"
                >
                    {loading ? "Initializing..." : "Enable Two-Factor Authentication"}
                </button>
            ) : (
                <div className="space-y-6">
                    <div className="flex flex-col items-center space-y-4">
                        <p className="text-sm text-center text-slate-600 dark:text-slate-400">
                            Scan this QR code with Google Authenticator or Authy
                        </p>
                        <div className="bg-white p-4 rounded-xl shadow-lg border border-slate-200">
                            <img src={`data:image/png;base64,${setupData.qr_code}`} alt="MFA QR Code" className="w-48 h-48" />
                        </div>
                        <p className="text-xs font-mono text-slate-500 bg-slate-100 dark:bg-slate-800 p-2 rounded">
                            Secret: {setupData.secret}
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-bold text-slate-700 dark:text-slate-300">Enter 6-digit backup code</label>
                        <div className="flex space-x-4">
                            <input
                                type="text"
                                maxLength={6}
                                value={mfaCode}
                                onChange={(e) => setMfaCode(e.target.value)}
                                placeholder="000000"
                                className="flex-1 bg-white/60 dark:bg-slate-800/60 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2 text-center text-2xl tracking-[0.5em] font-mono focus:ring-2 focus:ring-indigo-500"
                            />
                            <button
                                onClick={verifyMFA}
                                disabled={loading || mfaCode.length !== 6}
                                className="bg-green-600 hover:bg-green-700 text-white px-6 py-2 rounded-xl font-bold transition-all disabled:opacity-50"
                            >
                                {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : "Verify"}
                            </button>
                        </div>
                    </div>
                    {error && (
                        <div className="flex items-center space-x-2 text-red-500 text-sm mt-2">
                            <AlertCircle className="h-4 w-4" />
                            <span>{error}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
