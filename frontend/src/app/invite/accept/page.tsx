"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, EyeOff, Loader2, Lock, Mail, ShieldCheck, User, UserPlus, Users } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type InviteInfo = {
    email: string;
    company_name: string;
    company_website: string;
    invited_by: string;
    role_name: string;
    expires_at: string;
};

export default function InviteAcceptPage() {
    const params = useSearchParams();
    const router = useRouter();
    const { login } = useAuth();
    const token = params.get("token");

    const [inviteInfo, setInviteInfo] = useState<InviteInfo | null>(null);
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [firstName, setFirstName] = useState("");
    const [lastName, setLastName] = useState("");
    const [loading, setLoading] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [fetching, setFetching] = useState(true);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchInvite = async () => {
            if (!token) {
                setError("Missing invite token.");
                setFetching(false);
                return;
            }
            try {
                const res = await fetch(`${API_BASE}/auth/invites/accept?token=${encodeURIComponent(token)}`);
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.detail || "Invalid or expired invite link.");
                }
                const data: InviteInfo = await res.json();
                setInviteInfo(data);
                setUsername(data.email.split("@")[0]);
                setMessage(`You were invited by ${data.invited_by} to join ${data.company_name}.`);
            } catch (err) {
                setError((err as Error).message);
            } finally {
                setFetching(false);
            }
        };

        fetchInvite();
    }, [token]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!inviteInfo || !token) return;
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE}/auth/invites/accept`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    token,
                    email: inviteInfo.email,
                    username: username.trim(),
                    password,
                    first_name: firstName.trim() || undefined,
                    last_name: lastName.trim() || undefined,
                }),
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Could not accept invite.");
            }
            login(data.access_token);
            router.push("/");
        } catch (err) {
            setError((err as Error).message);
        } finally {
            setLoading(false);
        }
    };

    /* ── Loading state ─────────────────────────────────────────────── */
    if (fetching) {
        return (
            <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-900 via-violet-950 to-slate-900 p-4">
                <div className="pointer-events-none fixed inset-0 overflow-hidden">
                    <div className="absolute -top-40 -left-40 h-80 w-80 rounded-full bg-violet-600/20 blur-3xl" />
                    <div className="absolute -bottom-40 -right-40 h-80 w-80 rounded-full bg-blue-600/20 blur-3xl" />
                </div>
                <div className="relative flex flex-col items-center space-y-3 rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl">
                    <Loader2 className="h-10 w-10 animate-spin text-violet-400" />
                    <p className="text-sm font-semibold text-slate-300">Verifying your invite...</p>
                </div>
            </div>
        );
    }

    /* ── Error state ───────────────────────────────────────────────── */
    if (error && !inviteInfo) {
        return (
            <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-900 via-violet-950 to-slate-900 p-4">
                <div className="pointer-events-none fixed inset-0 overflow-hidden">
                    <div className="absolute -top-40 -left-40 h-80 w-80 rounded-full bg-violet-600/20 blur-3xl" />
                    <div className="absolute -bottom-40 -right-40 h-80 w-80 rounded-full bg-blue-600/20 blur-3xl" />
                </div>
                <div className="relative w-full max-w-md rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl">
                    <div className="flex flex-col items-center gap-3">
                        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500/10">
                            <ShieldCheck className="h-7 w-7 text-red-400" />
                        </div>
                        <p className="text-lg font-semibold text-white">Invite Invalid</p>
                        <p className="text-sm text-slate-400 text-center">{error}</p>
                        <button
                            onClick={() => router.push("/register")}
                            className="mt-4 w-full rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 font-bold text-white shadow-lg shadow-violet-500/30 hover:from-violet-500 hover:to-blue-500 hover:shadow-violet-500/50 transition-all"
                        >
                            Return to Register
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    /* ── Main form ─────────────────────────────────────────────────── */
    return (
        <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-slate-900 via-violet-950 to-slate-900 p-4 overflow-y-auto">
            {/* Decorative blobs */}
            <div className="pointer-events-none fixed inset-0 overflow-hidden">
                <div className="absolute -top-40 -left-40 h-80 w-80 rounded-full bg-violet-600/20 blur-3xl" />
                <div className="absolute -bottom-40 -right-40 h-80 w-80 rounded-full bg-blue-600/20 blur-3xl" />
            </div>

            <div className="relative w-full max-w-lg">
                {/* Brand header */}
                <div className="mb-8 text-center">
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-blue-600 shadow-lg shadow-violet-500/40">
                        <Users className="h-7 w-7 text-white" />
                    </div>
                    <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Invitation</p>
                    <h1 className="mt-1 text-3xl font-bold text-white tracking-tight">
                        Join <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">{inviteInfo!.company_name}</span>
                    </h1>
                    <p className="mt-2 text-sm text-slate-400">
                        Invited by <strong className="text-slate-200">{inviteInfo!.invited_by}</strong> as{" "}
                        <strong className="text-slate-200">{inviteInfo!.role_name}</strong>
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">
                        Expires {new Date(inviteInfo!.expires_at).toLocaleString()}
                    </p>
                </div>

                {/* Card */}
                <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl">
                    {message && (
                        <div className="mb-5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-4 py-3 text-sm text-emerald-400">
                            {message}
                        </div>
                    )}
                    {error && (
                        <div className="mb-5 rounded-xl bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
                            {error}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-5">
                        {/* Email (read-only) */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                Email
                            </label>
                            <div className="relative">
                                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type="email"
                                    value={inviteInfo!.email}
                                    disabled
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-3 pl-10 pr-4 text-slate-400 cursor-not-allowed"
                                />
                            </div>
                        </div>

                        {/* Username */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                Username
                            </label>
                            <div className="relative">
                                <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type="text"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    required
                                    placeholder="your_username"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-3 pl-10 pr-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                />
                            </div>
                        </div>

                        {/* First Name / Last Name */}
                        <div className="grid gap-4 sm:grid-cols-2">
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                    First Name <span className="normal-case text-slate-600">(optional)</span>
                                </label>
                                <input
                                    type="text"
                                    value={firstName}
                                    onChange={(e) => setFirstName(e.target.value)}
                                    placeholder="John"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                    Last Name <span className="normal-case text-slate-600">(optional)</span>
                                </label>
                                <input
                                    type="text"
                                    value={lastName}
                                    onChange={(e) => setLastName(e.target.value)}
                                    placeholder="Doe"
                                    className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-all"
                                />
                            </div>
                        </div>

                        {/* Password */}
                        <div className="space-y-1.5">
                            <label className="block text-xs font-semibold uppercase tracking-widest text-slate-400">
                                Password
                            </label>
                            <div className="relative">
                                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                                <input
                                    type={showPassword ? "text" : "password"}
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    placeholder="Create a password"
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

                        {/* Submit */}
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 py-3 font-bold text-white shadow-lg shadow-violet-500/30 hover:from-violet-500 hover:to-blue-500 hover:shadow-violet-500/50 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                            {loading ? "Joining..." : "Accept Invite & Sign In"}
                        </button>
                    </form>

                    <p className="mt-6 text-center text-sm text-slate-500">
                        Want to create your own company?{" "}
                        <a href="/register" className="font-semibold text-violet-400 hover:text-violet-300 transition-colors">
                            Sign up instead
                        </a>
                    </p>
                </div>
            </div>
        </div>
    );
}
