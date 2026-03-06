"use client";

import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
    User as UserIcon, Mail, Smartphone, Globe, Building2,
    Lock, Save, Loader2, CheckCircle2, AlertCircle, Camera,
    Shield, Trash2, ExternalLink, RefreshCw, XCircle
} from "lucide-react";
import clsx from "clsx";
import MFASetup from "@/components/MFASetup";
import { useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";

export default function ProfilePage() {
    const { user, token, refreshUser } = useAuth();
    const [isSaving, setIsSaving] = useState(false);
    const [isConnectingGoogle, setIsConnectingGoogle] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const searchParams = useSearchParams();
    const router = useRouter();

    useEffect(() => {
        const code = searchParams.get("code");
        if (code && token) {
            const finalizeGoogleAuth = async () => {
                setIsConnectingGoogle(true);
                try {
                    const res = await fetch("http://localhost:6060/auth/google/callback", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${token}`,
                        },
                        body: JSON.stringify({ code }),
                    });
                    if (res.ok) {
                        setMessage({ type: 'success', text: "Google account connected successfully! 📅" });
                        await refreshUser();
                        // Clean up URL
                        router.replace("/profile");
                    } else {
                        setMessage({ type: 'error', text: "Failed to connect Google account." });
                    }
                } catch (err) {
                    console.error("Finalizing Google Auth error:", err);
                    setMessage({ type: 'error', text: "An error occurred during Google connection." });
                } finally {
                    setIsConnectingGoogle(false);
                }
            };
            finalizeGoogleAuth();
        }
    }, [searchParams, token, refreshUser, router]);

    const [formData, setFormData] = useState({
        first_name: user?.first_name || "",
        last_name: user?.last_name || "",
        phone_number: user?.phone_number || "",
        company_name: user?.company_name || "",
        company_website: user?.company_website || "",
        profile_picture_url: user?.profile_picture_url || "",
    });

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setIsSaving(true);
        setMessage(null);

        const uploadData = new FormData();
        uploadData.append("file", file);

        try {
            const res = await fetch("http://localhost:6060/auth/upload-avatar", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
                body: uploadData,
            });

            if (res.ok) {
                const data = await res.json();
                setFormData(prev => ({ ...prev, profile_picture_url: data.url }));
                setMessage({ type: 'success', text: "Photo uploaded! Save profile to confirm. ✨" });
                await refreshUser();
            } else {
                setMessage({ type: 'error', text: "Failed to upload image." });
            }
        } catch (err) {
            setMessage({ type: 'error', text: "Upload error. Please try again." });
        } finally {
            setIsSaving(false);
        }
    };

    const handleConnectGoogle = async () => {
        setIsConnectingGoogle(true);
        try {
            const res = await fetch("http://localhost:6060/auth/google/url", {
                headers: { Authorization: `Bearer ${token}` },
            });
            const data = await res.json();
            if (data.auth_url) {
                // Open in a new window/tab
                const authWindow = window.open(data.auth_url, '_blank', 'width=600,height=700');

                // Set up a listener for the callback
                const checkWindow = setInterval(async () => {
                    if (authWindow?.closed) {
                        clearInterval(checkWindow);
                        setIsConnectingGoogle(false);
                        await refreshUser();
                    }
                }, 1000);
            }
        } catch (err) {
            console.error("Google Auth error:", err);
            setIsConnectingGoogle(false);
        }
    };

    const handleDisconnectGoogle = async () => {
        if (!window.confirm("Disconnect your Google account? You won't be able to generate Meet links automatically.")) return;

        try {
            const res = await fetch("http://localhost:6060/auth/google/disconnect", {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                setMessage({ type: 'success', text: "Google account disconnected." });
                await refreshUser();
            }
        } catch (err) {
            setMessage({ type: 'error', text: "Failed to disconnect." });
        }
    };

    const handleDeleteAccount = async () => {
        if (!window.confirm("ARE YOU SURE? This will permanently delete your account and you will be logged out immediately. This action cannot be undone.")) {
            return;
        }

        try {
            const res = await fetch("http://localhost:6060/auth/me", {
                method: "DELETE",
                headers: {
                    "Authorization": `Bearer ${token}`
                },
            });

            if (res.ok) {
                alert("Account deleted successfully.");
                localStorage.removeItem("access_token");
                window.location.href = "/register";
            } else {
                const errorData = await res.json();
                alert(`Error: ${errorData.detail || "Could not delete account"}`);
            }
        } catch (error) {
            console.error("Error deleting account:", error);
            alert("A network error occurred.");
        }
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsSaving(true);
        setMessage(null);

        try {
            const res = await fetch("http://localhost:6060/users/me", {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify(formData),
            });

            if (res.ok) {
                setMessage({ type: 'success', text: "Profile updated successfully! ✨" });
                await refreshUser();
            } else {
                const error = await res.json();
                setMessage({ type: 'error', text: error.detail || "Failed to update profile." });
            }
        } catch (err) {
            setMessage({ type: 'error', text: "Network error. Please try again." });
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 p-8 pt-24 text-slate-200">
            <div className="max-w-4xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">

                {/* Header Section */}
                <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-8 border-b border-white/10">
                    <div className="space-y-2">
                        <h1 className="text-4xl font-black tracking-tight bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">
                            My Profile
                        </h1>
                        <p className="text-slate-400 font-medium">Manage your personal and company identity.</p>
                    </div>

                    <div className="flex items-center space-x-2 text-xs font-bold uppercase tracking-widest text-slate-500 bg-white/5 px-4 py-2 rounded-full border border-white/10">
                        <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse mr-1" />
                        Account Status: Active
                    </div>
                </div>

                <form onSubmit={handleSave} className="grid grid-cols-1 lg:grid-cols-3 gap-8">

                    {/* Left Column: Avatar & Quick Info */}
                    <div className="lg:col-span-1 space-y-6">
                        <div className="glass-panel p-8 rounded-3xl flex flex-col items-center text-center space-y-4">
                            <div className="relative group">
                                <div className="h-32 w-32 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 p-1 shadow-2xl shadow-violet-500/20">
                                    <div className="h-full w-full rounded-full bg-slate-900 flex items-center justify-center overflow-hidden">
                                        {formData.profile_picture_url ? (
                                            <img src={formData.profile_picture_url} alt="Profile" className="h-full w-full object-cover" />
                                        ) : (
                                            <UserIcon size={48} className="text-slate-700" />
                                        )}
                                    </div>
                                </div>
                                <input
                                    type="file"
                                    id="profile-upload"
                                    className="hidden"
                                    accept="image/*"
                                    onChange={handleFileUpload}
                                />
                                <button
                                    type="button"
                                    onClick={() => document.getElementById('profile-upload')?.click()}
                                    className="absolute bottom-1 right-1 h-10 w-10 bg-slate-800 border border-slate-700 rounded-full flex items-center justify-center text-violet-400 hover:text-white hover:bg-violet-600 transition-all shadow-lg"
                                >
                                    <Camera size={18} />
                                </button>
                            </div>

                            <div className="space-y-1">
                                <h2 className="text-xl font-bold text-white">{user?.first_name || 'User'} {user?.last_name || ''}</h2>
                                <p className="text-xs font-mono text-violet-400 uppercase tracking-widest">@{user?.username}</p>
                            </div>

                            <div className="w-full pt-4 space-y-2 border-t border-white/5">
                                <div className="flex justify-between text-xs">
                                    <span className="text-slate-500">Role</span>
                                    <span className="text-slate-300 font-bold capitalize">{user?.role}</span>
                                </div>
                                <div className="flex justify-between text-xs">
                                    <span className="text-slate-500">Member Since</span>
                                    <span className="text-slate-300 font-bold">Jan 2026</span>
                                </div>
                            </div>
                        </div>

                        {/* Read-Only Alert */}
                        <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 flex gap-3">
                            <Lock className="text-amber-500 shrink-0" size={18} />
                            <p className="text-[11px] text-amber-200/80 leading-relaxed font-medium">
                                Username and email are immutable for security. Contact an admin if you need to update these.
                            </p>
                        </div>
                    </div>

                    {/* Right Column: Edit Fields */}
                    <div className="lg:col-span-2 space-y-6">
                        <div className="glass-panel p-8 rounded-3xl space-y-8">

                            {/* Personal Section */}
                            <div className="space-y-6">
                                <div className="flex items-center space-x-2 text-slate-400 border-b border-white/5 pb-2">
                                    <UserIcon size={16} />
                                    <span className="text-xs font-bold uppercase tracking-wider">Personal Information</span>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">First Name</label>
                                        <input
                                            type="text"
                                            value={formData.first_name}
                                            onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                                            className="w-full bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 transition-all"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">Last Name</label>
                                        <input
                                            type="text"
                                            value={formData.last_name}
                                            onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                                            className="w-full bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 transition-all"
                                        />
                                    </div>
                                    <div className="space-y-2 opacity-60">
                                        <label className="text-xs font-bold text-slate-500 ml-1 flex items-center">
                                            Email address <Lock size={10} className="ml-1" />
                                        </label>
                                        <div className="w-full bg-slate-900/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-400 cursor-not-allowed">
                                            {user?.email}
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">Phone Number</label>
                                        <input
                                            type="text"
                                            value={formData.phone_number}
                                            onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                                            className="w-full bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 transition-all"
                                        />
                                    </div>
                                </div>
                            </div>

                            {/* Company Section */}
                            <div className="space-y-6 pt-4">
                                <div className="flex items-center space-x-2 text-slate-400 border-b border-white/5 pb-2">
                                    <Building2 size={16} />
                                    <span className="text-xs font-bold uppercase tracking-wider">Company Branding</span>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">Company Name</label>
                                        <input
                                            type="text"
                                            value={formData.company_name}
                                            onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                                            placeholder="e.g. Yexis Electronics"
                                            className="w-full bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all placeholder:text-slate-600"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">Company Website</label>
                                        <div className="relative">
                                            <Globe size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-600" />
                                            <input
                                                type="url"
                                                value={formData.company_website}
                                                onChange={(e) => setFormData({ ...formData, company_website: e.target.value })}
                                                placeholder="https://example.com"
                                                className="w-full bg-slate-800/50 border border-slate-700 rounded-xl pl-12 pr-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all placeholder:text-slate-600"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Action Section */}
                            <div className="pt-6 flex items-center justify-between gap-4">
                                {message && (
                                    <div className={clsx(
                                        "flex items-center gap-2 text-sm font-medium animate-in fade-in slide-in-from-left-2",
                                        message.type === 'success' ? 'text-emerald-400' : 'text-red-400'
                                    )}>
                                        {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                                        {message.text}
                                    </div>
                                )}

                                <button
                                    type="submit"
                                    disabled={isSaving}
                                    className="ml-auto flex items-center gap-2 bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white font-bold py-3 px-8 rounded-xl transition-all shadow-xl shadow-violet-500/20 active:scale-95 disabled:opacity-50"
                                >
                                    {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                                    {isSaving ? "Saving..." : "Save Changes"}
                                </button>
                            </div>
                        </div>

                        {/* Connected Accounts Section */}
                        <div className="glass-panel p-8 rounded-3xl space-y-6">
                            <div className="flex items-center space-x-2 text-slate-400 border-b border-white/5 pb-2">
                                <Globe size={16} />
                                <span className="text-xs font-bold uppercase tracking-wider">Connected Accounts</span>
                            </div>

                            <div className="grid grid-cols-1 gap-4">
                                <div className="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/10 hover:border-violet-500/30 transition-all group">
                                    <div className="flex items-center space-x-4">
                                        <div className="h-10 w-10 flex items-center justify-center rounded-xl bg-white text-slate-900 font-bold shadow-lg">
                                            G
                                        </div>
                                        <div>
                                            <p className="font-bold text-white">Google Account</p>
                                            <p className="text-xs text-slate-500">
                                                {user?.google_account_email ? `Connected: ${user.google_account_email}` : "For Google Meet integration"}
                                            </p>
                                        </div>
                                    </div>

                                    {user?.google_account_email ? (
                                        <button
                                            type="button"
                                            onClick={handleDisconnectGoogle}
                                            className="flex items-center space-x-2 px-4 py-2 rounded-lg bg-red-500/10 text-red-400 text-xs font-bold hover:bg-red-500 hover:text-white transition-all"
                                        >
                                            <XCircle size={14} />
                                            <span>Disconnect</span>
                                        </button>
                                    ) : (
                                        <button
                                            type="button"
                                            onClick={handleConnectGoogle}
                                            disabled={isConnectingGoogle}
                                            className="flex items-center space-x-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-bold hover:bg-violet-500 transition-all shadow-lg shadow-violet-500/20 disabled:opacity-50"
                                        >
                                            {isConnectingGoogle ? <RefreshCw size={14} className="animate-spin" /> : <ExternalLink size={14} />}
                                            <span>Connect Google</span>
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* MFA Section */}
                        <div className="glass-panel p-8 rounded-3xl overflow-hidden relative">
                            <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
                                <Shield size={120} className="text-violet-400" />
                            </div>
                            <MFASetup />
                        </div>

                        {/* Danger Zone */}
                        <div className="rounded-3xl border border-red-500/20 bg-red-500/5 p-8 space-y-6">
                            <div className="flex items-center space-x-3">
                                <div className="h-10 w-10 rounded-xl bg-red-500 flex items-center justify-center text-white shadow-lg shadow-red-500/20">
                                    <Shield size={20} />
                                </div>
                                <div>
                                    <h3 className="text-xl font-bold text-red-400">Danger Zone</h3>
                                    <p className="text-sm text-slate-500">Security and account deletion</p>
                                </div>
                            </div>

                            <div className="p-6 rounded-2xl bg-slate-900/50 border border-red-500/10 flex flex-col md:flex-row items-center justify-between gap-6">
                                <div className="space-y-1 text-center md:text-left">
                                    <p className="font-bold text-white">Delete Account</p>
                                    <p className="text-sm text-slate-500">Once deleted, your data cannot be recovered. Please be certain.</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleDeleteAccount}
                                    className="flex items-center space-x-2 px-6 py-3 rounded-xl bg-red-600 text-white font-bold hover:bg-red-700 transition-all shadow-lg shadow-red-600/20"
                                >
                                    <Trash2 size={18} />
                                    <span>Delete My Account</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            </div>

            <style jsx>{`
        .glass-panel {
          background: rgba(30, 41, 59, 0.4);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(255, 255, 255, 0.05);
          box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .gradient-text {
          background: linear-gradient(135deg, #a78bfa 0%, #60a5fa 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
      `}</style>
        </div>
    );
}
