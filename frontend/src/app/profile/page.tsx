"use client";

import { useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
    User as UserIcon, Mail, Smartphone, Globe, Building2,
    Lock, Save, Loader2, CheckCircle2, AlertCircle, Camera,
    Shield, Trash2, ExternalLink, RefreshCw, XCircle,
    Eye, EyeOff, ShieldCheck, X, Clock
} from "lucide-react";
import clsx from "clsx";
import MFASetup from "@/components/MFASetup";
import { useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { maskEmail, maskPhone } from "@/utils/security";

export default function ProfilePage() {
    const { user, token, refreshUser, googleStatus, refreshGoogleStatus, showPersonalDetails, revealPersonalDetails, hidePersonalDetails, timeLeft } = useAuth();
    const [isSaving, setIsSaving] = useState(false);
    const [isConnectingGoogle, setIsConnectingGoogle] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const [isOtpModalOpen, setIsOtpModalOpen] = useState(false);
    const [otpValue, setOtpValue] = useState("");
    const [isRequestingOtp, setIsRequestingOtp] = useState(false);
    const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);
    const [otpError, setOtpError] = useState("");
    const searchParams = useSearchParams();
    const router = useRouter();

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

    // Add this near the top of ProfilePage component
    const hasHandledCode = useRef(false);

    useEffect(() => {
        const code = searchParams.get("code");
        if (code && token && !hasHandledCode.current) {
            hasHandledCode.current = true;  // ← blocks second fire
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
                        router.replace("/profile");
                    } else {
                        const err = await res.json();
                        setMessage({ type: 'error', text: err.detail || "Failed to connect Google account." });
                    }
                } catch (err) {
                    setMessage({ type: 'error', text: "An error occurred during Google connection." });
                } finally {
                    setIsConnectingGoogle(false);
                    await refreshGoogleStatus();
                }
            };
            finalizeGoogleAuth();
        }
    }, [searchParams, token]); // ← remove refreshUser and router from deps

    useEffect(() => {
        if (token) {
            refreshGoogleStatus();
        }
    }, [token]);

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
                        await refreshGoogleStatus();
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
                await refreshGoogleStatus();
            }
        } catch (err) {
            setMessage({ type: 'error', text: "Failed to disconnect." });
        }
    };

    const handleRequestReveal = async () => {
        if (showPersonalDetails) {
            hidePersonalDetails();
            return;
        }

        setIsOtpModalOpen(true);
        setIsRequestingOtp(true);
        setOtpError("");

        try {
            const res = await fetch("http://localhost:6060/auth/reveal/request", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) throw new Error("Failed to send OTP");
        } catch (err) {
            setOtpError("Failed to send verification code. Please try again.");
        } finally {
            setIsRequestingOtp(false);
        }
    };

    const handleVerifyReveal = async () => {
        setIsVerifyingOtp(true);
        setOtpError("");

        try {
            const res = await fetch("http://localhost:6060/auth/reveal/verify", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ token: otpValue }),
            });

            if (res.ok) {
                revealPersonalDetails();
                setIsOtpModalOpen(false);
                setOtpValue("");
            } else {
                const data = await res.json();
                setOtpError(data.detail || "Invalid code. Please try again.");
            }
        } catch (err) {
            setOtpError("Network error. Please try again.");
        } finally {
            setIsVerifyingOtp(false);
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
                                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                                    <div className="flex items-center space-x-2 text-slate-400">
                                        <UserIcon size={16} />
                                        <span className="text-xs font-bold uppercase tracking-wider">Personal Information</span>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        {showPersonalDetails && (
                                            <span className="flex items-center text-[10px] text-violet-400 font-bold uppercase tracking-tighter animate-pulse">
                                                <Clock size={10} className="mr-1" /> {Math.floor(timeLeft / 60)}:{(timeLeft % 60).toString().padStart(2, '0')}
                                            </span>
                                        )}
                                        <button
                                            type="button"
                                            onClick={handleRequestReveal}
                                            className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-violet-400 transition-all border border-white/10 group"
                                            title={showPersonalDetails ? "Hide private info" : "Reveal private info"}
                                        >
                                            {showPersonalDetails ? <EyeOff size={16} /> : <Eye size={16} />}
                                        </button>
                                    </div>
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
                                    <div className="space-y-2 opacity-80">
                                        <label className="text-xs font-bold text-slate-500 ml-1 flex items-center">
                                            Email address <Lock size={10} className="ml-1" />
                                        </label>
                                        <div className="w-full bg-slate-900/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-300 font-medium">
                                            {showPersonalDetails ? user?.email : maskEmail(user?.email || '')}
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1">Phone Number</label>
                                        <div className="relative group/input">
                                            <input
                                                type="text"
                                                value={showPersonalDetails ? formData.phone_number : maskPhone(formData.phone_number || '')}
                                                onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                                                disabled={!showPersonalDetails}
                                                className={clsx(
                                                    "w-full bg-slate-800/50 border rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 transition-all",
                                                    showPersonalDetails ? "border-slate-700" : "border-slate-800/50 text-slate-500 cursor-not-allowed select-none"
                                                )}
                                            />
                                            {!showPersonalDetails && (
                                                <div className="absolute inset-0 flex items-center justify-center bg-slate-900/40 backdrop-blur-[1px] rounded-xl opacity-0 group-hover/input:opacity-100 transition-opacity pointer-events-none">
                                                    <span className="text-[10px] font-bold text-violet-400 uppercase tracking-widest">Reveal to edit</span>
                                                </div>
                                            )}
                                        </div>
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

                            <div className="grid grid-cols-1 gap-6">
                                {/* Proactive Warning Banner */}
                                {googleStatus && googleStatus.status !== "valid" && googleStatus.status !== "disconnected" && (
                                    <div className={clsx(
                                        "p-4 rounded-2xl border flex items-start gap-3 animate-in fade-in slide-in-from-top-2",
                                        googleStatus.status === "expiring_soon" ? "bg-amber-500/10 border-amber-500/20 text-amber-200" : "bg-red-500/10 border-red-500/20 text-red-200"
                                    )}>
                                        <AlertCircle className={googleStatus.status === "expiring_soon" ? "text-amber-500" : "text-red-500"} size={20} />
                                        <div className="space-y-1">
                                            <p className="text-sm font-bold">
                                                {googleStatus.status === "expiring_soon" ? "Connection Expiring Soon" : "Connection Expired"}
                                            </p>
                                            <p className="text-xs opacity-80 leading-relaxed">
                                                {googleStatus.message} Reconnect now to ensure your Google Meet links are generated without issues.
                                            </p>
                                            <button 
                                                onClick={handleConnectGoogle}
                                                className="mt-2 text-xs font-black uppercase tracking-widest py-1.5 px-3 rounded-lg bg-white/10 hover:bg-white/20 transition-all border border-white/10"
                                            >
                                                Reconnect Now
                                            </button>
                                        </div>
                                    </div>
                                )}

                                <div className="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/10 hover:border-violet-500/30 transition-all group">
                                    <div className="flex items-center space-x-4">
                                        <div className="h-10 w-10 flex items-center justify-center rounded-xl bg-white text-slate-900 font-bold shadow-lg">
                                            G
                                        </div>
                                        <div>
                                            <div className="flex items-center gap-2">
                                                <p className="font-bold text-white">Google Calendar</p>
                                                {googleStatus && (
                                                    <span className={clsx(
                                                        "text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter",
                                                        googleStatus.status === "valid" ? "bg-emerald-500/20 text-emerald-400" :
                                                        googleStatus.status === "expiring_soon" ? "bg-amber-500/20 text-amber-400" :
                                                        googleStatus.status === "expired" ? "bg-red-500/20 text-red-400" :
                                                        "bg-slate-500/20 text-slate-400"
                                                    )}>
                                                        {googleStatus.status.replace("_", " ")}
                                                    </span>
                                                )}
                                            </div>
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

            {/* OTP Modal */}
            {isOtpModalOpen && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 animate-in fade-in duration-300">
                    <div className="w-full max-w-sm bg-slate-900 border border-slate-700 rounded-2xl p-6 shadow-2xl space-y-6 relative overflow-hidden animate-in zoom-in-95 duration-300">
                        {/* Modal Background Decor */}
                        <div className="absolute -top-12 -right-12 h-32 w-32 bg-violet-600/20 rounded-full blur-3xl" />

                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-bold text-white flex items-center gap-2">
                                <ShieldCheck className="text-violet-500" />
                                Identity Verification
                            </h3>
                            <button
                                type="button"
                                onClick={() => setIsOtpModalOpen(false)}
                                className="text-slate-400 hover:text-white transition-colors"
                                disabled={isVerifyingOtp}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <p className="text-sm text-slate-400">
                            We've sent a 6-digit verification code to <strong>{maskEmail(user?.email || '')}</strong>. Enter it below to reveal your sensitive details.
                        </p>

                        <div className="space-y-4">
                            <div className="relative">
                                <input
                                    type="text"
                                    maxLength={6}
                                    value={otpValue}
                                    onChange={(e) => setOtpValue(e.target.value.replace(/\D/g, ""))}
                                    placeholder="000000"
                                    className="w-full bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-center text-3xl tracking-[0.4em] font-mono text-white focus:outline-none focus:ring-2 focus:ring-violet-500 transition-all placeholder:text-slate-600"
                                    disabled={isVerifyingOtp || isRequestingOtp}
                                    autoFocus
                                />
                                {isRequestingOtp && (
                                    <div className="absolute inset-0 bg-slate-900/50 flex items-center justify-center rounded-xl">
                                        <Loader2 className="animate-spin text-violet-500" />
                                    </div>
                                )}
                            </div>

                            {otpError && (
                                <p className="text-xs text-red-500 text-center animate-in shake duration-300">{otpError}</p>
                            )}

                            <button
                                type="button"
                                onClick={handleVerifyReveal}
                                disabled={otpValue.length !== 6 || isVerifyingOtp || isRequestingOtp}
                                className="w-full py-3 bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-700 hover:to-blue-700 text-white rounded-xl font-bold transition-all disabled:opacity-50 disabled:scale-100 active:scale-95 flex items-center justify-center"
                            >
                                {isVerifyingOtp ? <Loader2 className="animate-spin mr-2" /> : "Verify & Reveal"}
                            </button>
                        </div>

                        <p className="text-[10px] text-center text-slate-500">
                            This code will expire in 10 minutes. Haven't received it? Check your spam folder.
                        </p>
                    </div>
                </div>
            )}

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
