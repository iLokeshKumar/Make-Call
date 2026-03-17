"use client";

import { useState, useEffect } from "react";
import { Save, Brain, Bell, Shield, Zap, Sun, Moon, Monitor, Loader2, CheckCircle2, PhoneForwarded } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { useAuth } from "@/context/AuthContext";

const themeOptions = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
] as const;

export default function SettingsPage() {
    const { theme, setTheme } = useTheme();
    const { user, token, sessionTimeout } = useAuth();
    const [systemInstruction, setSystemInstruction] = useState("");
    const [sttProvider, setSttProvider] = useState("deepgram");
    const [llmProvider, setLlmProvider] = useState("mistral");
    const [ttsProvider, setTtsProvider] = useState("cartesia");
    const [telephonyEngine, setTelephonyEngine] = useState("twilio");
    const [aiVerbosity, setAiVerbosity] = useState("2");
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);

    const API_BASE = "http://localhost:6060";

    useEffect(() => {
        const fetchSettings = async () => {
            try {
                const res = await fetch(`${API_BASE}/settings`, {
                    headers: { "Authorization": `Bearer ${token}` }
                });
                if (res.status === 401) {
                    sessionTimeout();
                    return;
                }
                const data = await res.json();
                setSystemInstruction(data.system_instruction || "");
                setSttProvider(data.stt_provider || "deepgram");
                setLlmProvider(data.llm_provider || "mistral");
                setTtsProvider(data.tts_provider || "cartesia");
                setTelephonyEngine(data.telephony_engine || "twilio");
                setAiVerbosity(data.ai_verbosity || "2");
            } catch (error) {
                console.error("Error fetching settings:", error);
            } finally {
                setLoading(false);
            }
        };
        fetchSettings();
    }, [token, sessionTimeout]);


    const handleSave = async () => {
        setSaving(true);
        setSaveSuccess(false);
        try {
            const res = await fetch(`${API_BASE}/settings`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify({
                    system_instruction: systemInstruction,
                    stt_provider: sttProvider,
                    llm_provider: llmProvider,
                    tts_provider: ttsProvider,
                    telephony_engine: telephonyEngine,
                    ai_verbosity: aiVerbosity
                }),
            });
            if (res.status === 401) {
                sessionTimeout();
                return;
            }
            if (res.ok) {
                setSaveSuccess(true);
                setTimeout(() => setSaveSuccess(false), 3000);
            }
        } catch (error) {
            console.error("Error saving settings:", error);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-6 pb-8 text-slate-800 dark:text-slate-100">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-4xl font-bold tracking-tight">
                        <span className="gradient-text">Settings</span>
                    </h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
                        Configure your CRM preferences and AI behavior
                    </p>
                </div>
                {saveSuccess && (
                    <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400 font-bold animate-in fade-in slide-in-from-right-4">
                        <CheckCircle2 className="h-5 w-5" />
                        <span>Settings Saved!</span>
                    </div>
                )}
            </div>

            <div className="space-y-6">
                {/* Theme Settings */}
                <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                    <div className="flex items-center space-x-3 mb-6">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-yellow-500 to-orange-500">
                            <Sun className="h-5 w-5 text-white" />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Appearance</h3>
                            <p className="text-sm text-slate-500 dark:text-slate-400">Choose your interface theme</p>
                        </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                        {themeOptions.map((option) => {
                            const Icon = option.icon;
                            const isActive = theme === option.value;

                            return (
                                <button
                                    key={option.value}
                                    onClick={() => setTheme(option.value)}
                                    className={`
                                        relative overflow-hidden rounded-xl p-4 border-2 transition-all duration-300
                                        ${isActive
                                            ? 'border-violet-600 bg-gradient-to-br from-violet-500/10 to-blue-500/10 shadow-lg'
                                            : 'border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-800/60 hover:border-violet-400 dark:hover:border-violet-500'
                                        }
                                    `}
                                >
                                    <div className="flex flex-col items-center space-y-2">
                                        <div className={`
                                            flex h-12 w-12 items-center justify-center rounded-xl transition-all
                                            ${isActive
                                                ? 'bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50'
                                                : 'bg-slate-100 dark:bg-slate-700'
                                            }
                                        `}>
                                            <Icon className={`h-6 w-6 ${isActive ? 'text-white' : 'text-slate-600 dark:text-slate-300'}`} />
                                        </div>
                                        <span className={`text-sm font-semibold ${isActive ? 'text-violet-700 dark:text-violet-400' : 'text-slate-700 dark:text-slate-300'}`}>
                                            {option.label}
                                        </span>
                                    </div>
                                    {isActive && (
                                        <div className="absolute top-2 right-2 h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                                    )}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Telephony Configuration */}
                {user?.role === "admin" && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600">
                                <Zap className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Telephony Engine</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Choose your call routing provider</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <button
                                onClick={() => setTelephonyEngine("twilio")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "twilio"
                                        ? 'border-red-500 bg-red-500/5 dark:bg-red-500/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "twilio" ? 'bg-red-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <Bell className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Twilio</p>
                                    <p className="text-xs text-slate-500">Global Coverage</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("enablex")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "enablex"
                                        ? 'border-indigo-600 bg-indigo-600/5 dark:bg-indigo-600/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "enablex" ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <Zap className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">EnableX</p>
                                    <p className="text-xs text-slate-500">India Optimized</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("exotel")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "exotel"
                                        ? 'border-orange-500 bg-orange-500/5 dark:bg-orange-500/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "exotel" ? 'bg-orange-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <PhoneForwarded className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Exotel</p>
                                    <p className="text-xs text-slate-500">India Optimized PCM</p>
                                </div>
                            </button>
                        </div>
                    </div>
                )}

                {/* AI Configuration */}
                {user?.role === "admin" && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-pink-500">
                                <Brain className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Digital Sales Representative (Rio)</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Modular Engine Configuration</p>
                            </div>
                        </div>

                        <div className="space-y-8">
                            {/* Modular Providers Selection */}
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                {/* STT Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">STT (Hearing)</label>
                                    <select
                                        value={sttProvider}
                                        onChange={(e) => setSttProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="deepgram">Deepgram Nova-2</option>
                                        <option value="sarvam">Sarvam Bulbul</option>
                                        <option value="cartesia">Cartesia Sonic</option>
                                    </select>
                                </div>

                                {/* LLM Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">LLM (Thinking)</label>
                                    <select
                                        value={llmProvider}
                                        onChange={(e) => setLlmProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="mistral">Mistral Large</option>
                                        <option value="anthropic">Claude 3.5 Sonnet</option>
                                        <option value="google">Gemini 1.5 Flash</option>
                                        <option value="perplexity">Perplexity AI</option>
                                    </select>
                                </div>

                                {/* TTS Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">TTS (Speaking)</label>
                                    <select
                                        value={ttsProvider}
                                        onChange={(e) => setTtsProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="cartesia">Cartesia Sonic</option>
                                        <option value="elevenlabs">ElevenLabs Turbo</option>
                                        <option value="sarvam">Sarvam Bulbul</option>
                                        <option value="deepgram">Deepgram Aura</option>
                                    </select>
                                </div>
                            </div>

                            {/* Response Verbosity */}
                            <div className="space-y-4">
                                <div className="flex items-center justify-between ml-1">
                                    <label htmlFor="response-verbosity" className="text-sm font-bold text-slate-700 dark:text-slate-300">Response Verbosity</label>
                                    <span className={`text-xs font-bold px-2 py-1 rounded-md ${aiVerbosity === "1" ? "bg-red-500/10 text-red-500" :
                                        aiVerbosity === "3" ? "bg-blue-500/10 text-blue-500" :
                                            "bg-green-500/10 text-green-500"
                                        }`}>
                                        {aiVerbosity === "1" ? "Ultra-Concise" : aiVerbosity === "3" ? "Detailed" : "Balanced"}
                                    </span>
                                </div>
                                <div className="relative pt-1 px-1">
                                    <input
                                        id="response-verbosity"
                                        type="range"
                                        min="1"
                                        max="3"
                                        step="1"
                                        value={aiVerbosity}
                                        onChange={(e) => setAiVerbosity(e.target.value)}
                                        className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-violet-600"
                                    />
                                    <div className="flex justify-between mt-2 px-1">
                                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Brevity</span>
                                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Depth</span>
                                    </div>
                                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-2 italic ml-1">
                                        {aiVerbosity === "1" && "Rio will stick to 1 short sentence or even 1 word."}
                                        {aiVerbosity === "2" && "Rio will provide concise 1-3 sentence answers."}
                                        {aiVerbosity === "3" && "Rio will provide elaborate, detailed explanations."}
                                    </p>
                                </div>
                            </div>

                            {/* System Instructions */}
                            <div className="space-y-2">
                                <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">System Instructions / Script</label>
                                {loading ? (
                                    <div className="h-64 rounded-xl border border-dashed border-slate-300 dark:border-slate-600 flex items-center justify-center bg-slate-50 dark:bg-slate-900/40">
                                        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
                                    </div>
                                ) : (
                                    <textarea
                                        value={systemInstruction}
                                        onChange={(e) => setSystemInstruction(e.target.value)}
                                        className="w-full h-80 rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-4 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm font-mono text-sm leading-relaxed"
                                        placeholder="Paste your AI persona script here..."
                                    />
                                )}
                            </div>
                        </div>
                    </div>
                )}


                {/* Integrations */}
                {user?.role === "admin" && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500">
                                <Zap className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Integrations</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Connected services status</p>
                            </div>
                        </div>

                        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                            <div className="rounded-xl bg-gradient-to-br from-purple-500/10 to-pink-500/10 p-4 border border-purple-200/50 dark:border-purple-500/30 font-medium">
                                <div className="flex items-center justify-between mb-2">
                                    <p className="text-slate-900 dark:text-slate-100 italic">Twilio</p>
                                    <span className="inline-flex items-center rounded-full bg-green-50 dark:bg-green-900/30 px-2 py-1 text-xs font-semibold text-green-700 dark:text-green-400 ring-1 ring-green-600/20">
                                        ● Active
                                    </span>
                                </div>
                                <p className="text-sm text-slate-600 dark:text-slate-400">Voice & SMS Gateway</p>
                            </div>

                            <div className="rounded-xl bg-gradient-to-br from-indigo-500/10 to-blue-500/10 p-4 border border-indigo-200/50 dark:border-indigo-500/30 font-medium">
                                <div className="flex items-center justify-between mb-2">
                                    <p className="text-slate-900 dark:text-slate-100 italic">EnableX</p>
                                    <span className="inline-flex items-center rounded-full bg-green-50 dark:bg-green-900/30 px-2 py-1 text-xs font-semibold text-green-700 dark:text-green-400 ring-1 ring-green-600/20">
                                        ● Connected
                                    </span>
                                </div>
                                <p className="text-sm text-slate-600 dark:text-slate-400">India Voice Engine</p>
                            </div>

                            <div className="rounded-xl bg-gradient-to-br from-blue-500/10 to-cyan-500/10 p-4 border border-blue-200/50 dark:border-blue-500/30 font-medium md:col-span-2 lg:col-span-1">
                                <div className="flex items-center justify-between mb-2">
                                    <p className="text-slate-900 dark:text-slate-100 italic">Gemini AI</p>
                                    <span className="inline-flex items-center rounded-full bg-green-50 dark:bg-green-900/30 px-2 py-1 text-xs font-semibold text-green-700 dark:text-green-400 ring-1 ring-green-600/20">
                                        ● Active
                                    </span>
                                </div>
                                <p className="text-sm text-slate-600 dark:text-slate-400">Multimodal Assistant</p>
                            </div>
                        </div>
                    </div>
                )}

                {/* Save Button */}
                {user?.role === "admin" && (
                    <div className="flex justify-end pt-12">
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className={`group relative overflow-hidden rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-8 py-3 font-semibold text-white shadow-lg shadow-violet-500/50 hover:shadow-xl hover:scale-105 transition-all duration-300 disabled:opacity-50 disabled:scale-100`}
                        >
                            <div className="absolute inset-0 bg-white/20 transform scale-x-0 group-hover:scale-x-100 transition-transform origin-left duration-300" />
                            <div className="relative flex items-center space-x-2">
                                {saving ? <Loader2 className="h-5 w-5 animate-spin" /> : <Save className="h-5 w-5" />}
                                <span>{saving ? 'Saving...' : 'Save Changes'}</span>
                            </div>
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
