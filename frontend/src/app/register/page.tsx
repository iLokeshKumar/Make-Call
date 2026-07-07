"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, Building2, CheckCircle2, Eye, EyeOff, Loader2, Lock, Mail, User } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type RegisterResponse = {
    detail?: string | { message?: string };
    message?: string;
};

function getResponseMessage(data: RegisterResponse, fallback: string) {
    if (typeof data.message === "string" && data.message.trim()) return data.message;
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
    if (data.detail?.message?.trim()) return data.detail.message;
    return fallback;
}

export default function RegisterPage() {
    const [companyName, setCompanyName] = useState("");
    const [companySlug, setCompanySlug] = useState("");
    const [username, setUsername] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [firstName, setFirstName] = useState("");
    const [lastName, setLastName] = useState("");
    const [errorMessage, setErrorMessage] = useState("");
    const [successMessage, setSuccessMessage] = useState("");
    const [registeredEmail, setRegisteredEmail] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [passwordFocused, setPasswordFocused] = useState(false);

    const CONSUMER_DOMAINS = ["gmail.com","yahoo.com","hotmail.com","outlook.com","live.com",
        "icloud.com","protonmail.com","proton.me","aol.com","msn.com","googlemail.com",
        "ymail.com","rocketmail.com","hotmail.co.uk","hotmail.fr","me.com","mac.com",
        "tutanota.com","fastmail.com","zoho.com","gmx.com","gmx.net","inbox.com",
        "mail.com","hushmail.com"];
    const emailDomain = email.split("@")[1]?.toLowerCase() ?? "";
    const emailWarning = emailDomain && CONSUMER_DOMAINS.includes(emailDomain)
        ? "Please use your company or work email, not a personal one."
        : null;

    const PASSWORD_RULES = [
        { label: "6+ characters",      ok: password.length >= 6 },
        { label: "Uppercase letter",   ok: /[A-Z]/.test(password) },
        { label: "Lowercase letter",   ok: /[a-z]/.test(password) },
        { label: "Number",             ok: /\d/.test(password) },
        { label: "Special character",  ok: /[!@#$%^&*()\-_=+[\]{}|;:'",.<>/?`~]/.test(password) },
    ];
    const strength = PASSWORD_RULES.filter(r => r.ok).length;
    const strengthColor = strength <= 1 ? "bg-red-500" : strength <= 2 ? "bg-orange-500" : strength <= 3 ? "bg-yellow-500" : strength <= 4 ? "bg-lime-500" : "bg-green-500";

    const derivedSlug = useMemo(() => {
        if (companySlug.trim()) return companySlug.trim().toLowerCase().replace(/\s+/g, "-");
        return companyName.trim().toLowerCase().replace(/\s+/g, "-");
    }, [companySlug, companyName]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setErrorMessage("");
        setSuccessMessage("");
        setIsLoading(true);
        try {
            const targetEmail = email.trim();
            const res = await apiFetch(`${API_BASE}/companies/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    company_name: companyName,
                    company_slug: derivedSlug,
                    username,
                    admin_email: email,
                    email,
                    password,
                    first_name: firstName,
                    last_name: lastName,
                }),
            });
            const data = await res.json().catch(() => ({} as RegisterResponse));
            if (!res.ok) {
                throw new Error(getResponseMessage(data, "Registration failed. Please check the details and try again."));
            }
            setRegisteredEmail(targetEmail);
            setSuccessMessage(getResponseMessage(data, "Account created successfully. Verification link sent to your email."));
        } catch (err: unknown) {
            setErrorMessage(err instanceof Error ? err.message : "Registration failed. Please try again.");
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

            <div className="relative w-full max-w-lg my-8">
                {/* Logo / Brand */}
                <div className="mb-8 text-center">
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-blue-600 shadow-lg shadow-violet-500/40">
                        <span className="text-2xl font-black text-white">R</span>
                    </div>
                    <h1 className="text-3xl font-bold text-white tracking-tight">Create your account</h1>
                    <p className="mt-1 text-slate-400 text-sm">Get started with Rio CRM</p>
                </div>

                {/* Card */}
                <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl">
                    {(successMessage || errorMessage) && (
                        <div className={`mb-5 rounded-xl border px-4 py-4 text-sm ${
                            successMessage
                                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
                                : "bg-red-500/10 border-red-500/20 text-red-300"
                        }`}>
                            <div className="flex items-start gap-3">
                                {successMessage ? (
                                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
                                ) : (
                                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" />
                                )}
                                <div>
                                    <p className={`font-semibold ${successMessage ? "text-emerald-200" : "text-red-200"}`}>
                                        {successMessage ? "Registration successful" : "Registration failed"}
                                    </p>
                                    <p className="mt-1 opacity-90">{successMessage || errorMessage}</p>
                                    {successMessage && (
                                        <p className="mt-1 opacity-80">
                                            Check {registeredEmail || "your inbox"} and verify your email before signing in.
                                        </p>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-4">
                        {/* Company row */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                    Company Name
                                </label>
                                <div className="relative">
                                    <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                    <input
                                        type="text"
                                        required
                                        value={companyName}
                                        onChange={(e) => setCompanyName(e.target.value)}
                                        placeholder="Yexis Electronics"
                                        className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                    />
                                </div>
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                    Slug <span className="text-slate-600 normal-case">(auto)</span>
                                </label>
                                <input
                                    type="text"
                                    value={companySlug}
                                    onChange={(e) => setCompanySlug(e.target.value)}
                                    placeholder={derivedSlug || "yexis-electronics"}
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 px-4 text-white placeholder-slate-600 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm font-mono"
                                />
                            </div>
                        </div>

                        {/* Name row */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">First Name</label>
                                <input
                                    type="text"
                                    value={firstName}
                                    onChange={(e) => setFirstName(e.target.value)}
                                    placeholder="John"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 px-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">Last Name</label>
                                <input
                                    type="text"
                                    value={lastName}
                                    onChange={(e) => setLastName(e.target.value)}
                                    placeholder="Doe"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 px-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                />
                            </div>
                        </div>

                        {/* Username */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">Username</label>
                            <div className="relative">
                                <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type="text"
                                    required
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    placeholder="johndoe"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                />
                            </div>
                            <p className="text-xs text-slate-600">Used to log in · must be unique</p>
                        </div>

                        {/* Email */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">Work Email</label>
                            <div className="relative">
                                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type="email"
                                    required
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    placeholder="john@yexis.com"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                />
                            </div>
                            {emailWarning && (
                                <p className="flex items-center gap-1.5 text-xs text-amber-400">
                                    <span>⚠</span>{emailWarning}
                                </p>
                            )}
                        </div>

                        {/* Password */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">Password</label>
                            <div className="relative">
                                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type={showPassword ? "text" : "password"}
                                    required
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    onFocus={() => setPasswordFocused(true)}
                                    onBlur={() => setPasswordFocused(false)}
                                    placeholder="••••••••"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-10 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all text-sm"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                                >
                                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                            </div>
                            {(passwordFocused || password.length > 0) && (
                                <div className="space-y-2 pt-0.5">
                                    {/* Strength bar */}
                                    <div className="flex gap-1">
                                        {[1,2,3,4,5].map(i => (
                                            <div
                                                key={i}
                                                className={`h-1 flex-1 rounded-full transition-all duration-200 ${i <= strength ? strengthColor : "bg-white/10"}`}
                                            />
                                        ))}
                                    </div>
                                    {/* Rule checklist */}
                                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                                        {PASSWORD_RULES.map(rule => (
                                            <span key={rule.label} className={`flex items-center gap-1 text-xs transition-colors ${rule.ok ? "text-green-400" : "text-slate-500"}`}>
                                                {rule.ok ? "✓" : "○"} {rule.label}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>

                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 py-3 font-bold text-white shadow-lg shadow-violet-500/30 hover:from-violet-500 hover:to-blue-500 transition-all disabled:opacity-50 flex items-center justify-center gap-2 mt-2"
                        >
                            {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
                            Create Account
                        </button>
                    </form>

                    <p className="mt-6 text-center text-sm text-slate-500">
                        Already have an account?{" "}
                        <Link href="/login" className="font-semibold text-violet-400 hover:text-violet-300 transition-colors">
                            Sign in
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
