"use client";

import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import Link from "next/link";
import { Eye, EyeOff, Loader2, Lock, User } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

export default function LoginPage() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [mfaRequired, setMfaRequired] = useState(false);
    const [mfaToken, setMfaToken] = useState("");
    const [unverified, setUnverified] = useState(false);
    const [verificationEmail, setVerificationEmail] = useState("");
    const [successMessage, setSuccessMessage] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [isResendLoading, setIsResendLoading] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const { login } = useAuth();

    const handleResend = async () => {
        const targetEmail = verificationEmail || username;
        if (!targetEmail) { setError("Enter the email you used to register."); return; }
        setIsResendLoading(true);
        setError("");
        setSuccessMessage("");
        try {
            const res = await fetch(`${API_BASE}/auth/verify-email/resend`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: targetEmail }),
            });
            const data = await res.json();
            if (res.ok) setSuccessMessage(data.message || "Verification link sent.");
            else setError(data.detail || "Failed to resend link.");
        } catch { setError("Failed to resend link."); }
        finally { setIsResendLoading(false); }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        setUnverified(false);
        setSuccessMessage("");
        setIsLoading(true);
        try {
            const formData = new URLSearchParams();
            formData.append("username", username);
            formData.append("password", password);
            const url = new URL(`${API_BASE}/token`);
            if (mfaRequired && mfaToken) url.searchParams.append("mfa_token", mfaToken);
            const res = await apiFetch(url.toString(), {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData,
            });
            const data = await res.json();
            if (!res.ok) {
                const detail = typeof data.detail === "object" ? data.detail : undefined;
                const errorCode = detail?.code ?? data.detail;
                const errorMessage = detail?.message ?? data.detail;
                if (res.status === 403 && errorCode === "MFA_REQUIRED") { setMfaRequired(true); return; }
                if (res.status === 403 && errorCode === "EMAIL_UNVERIFIED") {
                    setError("Please verify your email before logging in.");
                    setUnverified(true);
                    setVerificationEmail(detail?.email ?? username);
                    return;
                }
                throw new Error(errorMessage || "Invalid username or password");
            }
            await login();
        } catch (err: any) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-900 via-violet-950 to-slate-900 p-4 overflow-y-auto">
            {/* Decorative blobs */}
            <div className="pointer-events-none fixed inset-0 overflow-hidden">
                <div className="absolute -top-40 -left-40 h-80 w-80 rounded-full bg-violet-600/20 blur-3xl" />
                <div className="absolute -bottom-40 -right-40 h-80 w-80 rounded-full bg-blue-600/20 blur-3xl" />
            </div>

            <div className="relative w-full max-w-md">
                {/* Logo / Brand */}
                <div className="mb-8 text-center">
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-blue-600 shadow-lg shadow-violet-500/40">
                        <span className="text-2xl font-black text-white">R</span>
                    </div>
                    <h1 className="text-3xl font-bold text-white tracking-tight">Welcome back</h1>
                    <p className="mt-1 text-slate-400 text-sm">Sign in to Rio CRM</p>
                </div>

                {/* Card */}
                <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl">
                    {error && (
                        <div className="mb-4 flex items-center justify-between gap-3 rounded-xl bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
                            <span>{error}</span>
                            {unverified && (
                                <button onClick={handleResend} disabled={isResendLoading}
                                    className="shrink-0 font-semibold underline hover:text-red-300 disabled:opacity-50">
                                    {isResendLoading ? "Sending…" : "Resend Link"}
                                </button>
                            )}
                        </div>
                    )}
                    {successMessage && (
                        <div className="mb-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-4 py-3 text-sm text-emerald-400">
                            {successMessage}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-5">
                        {!mfaRequired ? (
                            <>
                                <div className="space-y-1.5">
                                    <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                        Username
                                    </label>
                                    <div className="relative">
                                        <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                        <input
                                            type="text"
                                            required
                                            autoFocus
                                            value={username}
                                            onChange={(e) => setUsername(e.target.value)}
                                            placeholder="your_username"
                                            className="w-full rounded-xl border border-white/10 bg-white/5 py-3 pl-10 pr-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                        />
                                    </div>
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                        Password
                                    </label>
                                    <div className="relative">
                                        <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                        <input
                                            type={showPassword ? "text" : "password"}
                                            required
                                            value={password}
                                            onChange={(e) => setPassword(e.target.value)}
                                            placeholder="••••••••"
                                            className="w-full rounded-xl border border-white/10 bg-white/5 py-3 pl-10 pr-10 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowPassword(!showPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                                        >
                                            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                        </button>
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                    6-Digit Authenticator Code
                                </label>
                                <input
                                    type="text"
                                    required
                                    maxLength={6}
                                    value={mfaToken}
                                    onChange={(e) => setMfaToken(e.target.value)}
                                    placeholder="000000"
                                    autoFocus
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-center text-2xl tracking-[0.5em] font-mono text-white placeholder-slate-600 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                />
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 py-3 font-bold text-white shadow-lg shadow-violet-500/30 hover:from-violet-500 hover:to-blue-500 hover:shadow-violet-500/50 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                            {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
                            {mfaRequired ? "Verify & Sign In" : "Sign In"}
                        </button>

                        {mfaRequired && (
                            <button type="button" onClick={() => setMfaRequired(false)}
                                className="w-full text-sm text-slate-400 hover:text-violet-400 transition-colors">
                                ← Back to Login
                            </button>
                        )}
                    </form>

                    <p className="mt-6 text-center text-sm text-slate-500">
                        Don't have an account?{" "}
                        <Link href="/register" className="font-semibold text-violet-400 hover:text-violet-300 transition-colors">
                            Sign up
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
