"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Loader2, ShieldCheck, UserPlus } from "lucide-react";
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

    if (fetching) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
                <div className="flex flex-col items-center space-y-3 rounded-2xl bg-slate-900 border border-slate-800 p-8 shadow-2xl">
                    <Loader2 className="h-10 w-10 animate-spin text-violet-400" />
                    <p className="text-sm font-semibold text-slate-300">Verifying your invite...</p>
                </div>
            </div>
        );
    }

    if (error || !inviteInfo) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
                <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-800 p-8 shadow-2xl">
                    <div className="flex flex-col items-center gap-3">
                        <ShieldCheck className="h-12 w-12 text-red-400" />
                        <p className="text-lg font-semibold text-white">Invite Invalid</p>
                        <p className="text-sm text-slate-400 text-center">{error || "This invite link cannot be used."}</p>
                        <button
                            onClick={() => router.push("/register")}
                            className="mt-4 rounded-xl bg-violet-600 hover:bg-violet-700 px-4 py-2 text-white font-semibold transition"
                        >
                            Return to Register
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4 py-10">
            <div className="w-full max-w-lg space-y-6 rounded-3xl bg-slate-900 border border-slate-800 p-8 shadow-2xl">
                <div className="space-y-2">
                    <p className="text-xs text-slate-500 uppercase tracking-[0.3em]">Invitation</p>
                    <h1 className="text-3xl font-bold text-white">
                        Join <span className="text-violet-400">{inviteInfo.company_name}</span>
                    </h1>
                    <p className="text-sm text-slate-400">
                        Invited by <strong className="text-slate-200">{inviteInfo.invited_by}</strong> for the role{" "}
                        <strong className="text-slate-200">{inviteInfo.role_name}</strong> · expires{" "}
                        {new Date(inviteInfo.expires_at).toLocaleString()}
                    </p>
                </div>

                {message && (
                    <div className="rounded-2xl bg-emerald-500/10 border border-emerald-500/20 p-4 text-sm text-emerald-400">
                        {message}
                    </div>
                )}

                <form onSubmit={handleSubmit} className="grid gap-4">
                    <div>
                        <label className="text-xs font-semibold uppercase text-slate-500">Email</label>
                        <input
                            type="email"
                            value={inviteInfo.email}
                            disabled
                            className="w-full rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-400 cursor-not-allowed"
                        />
                    </div>
                    <div>
                        <label className="text-xs font-semibold uppercase text-slate-500">Username</label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            required
                            className="w-full rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                        />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                        <div>
                            <label className="text-xs font-semibold uppercase text-slate-500">First Name <span className="normal-case text-slate-600">(optional)</span></label>
                            <input
                                type="text"
                                value={firstName}
                                onChange={(e) => setFirstName(e.target.value)}
                                className="w-full rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                            />
                        </div>
                        <div>
                            <label className="text-xs font-semibold uppercase text-slate-500">Last Name <span className="normal-case text-slate-600">(optional)</span></label>
                            <input
                                type="text"
                                value={lastName}
                                onChange={(e) => setLastName(e.target.value)}
                                className="w-full rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                            />
                        </div>
                    </div>
                    <div>
                        <label className="text-xs font-semibold uppercase text-slate-500">Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            className="w-full rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                        />
                    </div>
                    {error && <p className="text-xs text-red-400">{error}</p>}
                    <button
                        type="submit"
                        disabled={loading}
                        className="mt-2 flex items-center justify-center rounded-2xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/30 hover:from-violet-700 hover:to-blue-700 disabled:opacity-60 transition"
                    >
                        {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><UserPlus className="mr-2 h-4 w-4" />Accept Invite &amp; Sign In</>}
                    </button>
                </form>
            </div>
        </div>
    );
}
