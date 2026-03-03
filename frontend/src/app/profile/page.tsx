"use client";

import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
    User as UserIcon, Mail, Smartphone, Globe, Building2,
    Lock, Save, Loader2, CheckCircle2, AlertCircle, Camera
} from "lucide-react";
import clsx from "clsx";

export default function ProfilePage() {
    const { user, token, refreshUser } = useAuth();
    const [isSaving, setIsSaving] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

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
