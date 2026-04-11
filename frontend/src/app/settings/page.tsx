"use client";

import { useState, useEffect } from "react";
import { Save, Brain, Bell, Zap, Sun, Moon, Monitor, Loader2, CheckCircle2, PhoneForwarded, KeyRound, Settings, Eye, EyeOff, Mail, RefreshCw } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { useAuth } from "@/context/AuthContext";

const themeOptions = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
] as const;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";
const CRM_BASE = `${API_BASE}/crm`;

const COMPANY_SETTING_KEYS = {
    systemInstruction: ["SYSTEM_INSTRUCTION", "system_instruction"],
    sttProvider: ["STT_PROVIDER", "stt_provider"],
    llmProvider: ["LLM_PROVIDER", "llm_provider"],
    ttsProvider: ["TTS_PROVIDER", "tts_provider"],
    telephonyEngine: ["TELEPHONY_ENGINE", "telephony_engine"],
    aiVerbosity: ["AI_VERBOSITY", "ai_verbosity"],
} as const;

const INTEGRATION_KEY_ALIASES: Record<string, string> = {
    PHONE_NUMBER_FROM: "TWILIO_PHONE_NUMBER",
    WHATSAPP_NUMBER_FROM: "WHATSAPP_NUMBER",
    SMTP_SERVER: "SMTP_HOST",
};

function readSettingValue(
    settings: Record<string, string>,
    keys: readonly [string, string],
    fallback: string
) {
    return settings[keys[0]] ?? settings[keys[1]] ?? fallback;
}

function normalizeIntegrationValues(keysData: Record<string, string>) {
    return {
        ...keysData,
        PHONE_NUMBER_FROM: keysData.PHONE_NUMBER_FROM ?? keysData.TWILIO_PHONE_NUMBER ?? "",
        WHATSAPP_NUMBER_FROM: keysData.WHATSAPP_NUMBER_FROM ?? keysData.WHATSAPP_NUMBER ?? "",
        SMTP_SERVER: keysData.SMTP_SERVER ?? keysData.SMTP_HOST ?? "",
        SARVAM_STT_MODEL:
            keysData.SARVAM_STT_MODEL ||
            keysData.SMALLEST_STT_MODEL ||
            "",
        SARVAM_VOICE_ID: keysData.SARVAM_VOICE_ID || keysData.SMALLEST_VOICE_ID || "",
    };
}

function isMaskedValue(value: string) {
    return value.startsWith("***") || value.includes("...");
}

function isSecretIntegrationKey(key: string) {
    return /(API_KEY|AUTH_TOKEN|PASSWORD|TOKEN|SECRET)/.test(key);
}

type RoleOption = {
    id: number;
    name: string;
    description?: string;
};

export default function SettingsPage() {
    const { theme, setTheme } = useTheme();
    const { user, token, sessionTimeout } = useAuth();
    const [systemInstruction, setSystemInstruction] = useState("");
    const [sttProvider, setSttProvider] = useState("deepgram");
    const [llmProvider, setLlmProvider] = useState("mistral");
    const [ttsProvider, setTtsProvider] = useState("cartesia");
    const [telephonyEngine, setTelephonyEngine] = useState("twilio");
    const [aiVerbosity, setAiVerbosity] = useState("1");
    
    // API Keys State
    const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
    
    // UI State
    const [activeTab, setActiveTab] = useState("general");
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
    const [roles, setRoles] = useState<RoleOption[]>([]);
    const [inviteEmail, setInviteEmail] = useState("");
    const [inviteRoleId, setInviteRoleId] = useState<number | null>(null);
    const [inviteExpiresHours, setInviteExpiresHours] = useState(72);
    const [inviteMessage, setInviteMessage] = useState<string | null>(null);
    const [isInviting, setIsInviting] = useState(false);
    const hasAdminAccess = user?.role === "company_admin" || user?.role === "company_owner";

    // Competitor tab state
    const [competitorNames, setCompetitorNames] = useState("");
    const [savingCompetitors, setSavingCompetitors] = useState(false);
    const [competitorSaved, setCompetitorSaved] = useState(false);
    const [competitorSummary, setCompetitorSummary] = useState<Array<{ competitor: string; count: number; counter_script?: string }>>([]);
    const [counterScripts, setCounterScripts] = useState<Record<string, string>>({});
    const [savingScript, setSavingScript] = useState<string | null>(null);
    const [newCompetitorName, setNewCompetitorName] = useState("");

    // Per-user AI/preference settings (accessible to all roles)
    const [myAiPrompt, setMyAiPrompt] = useState("");
    const [myAiVerbosity, setMyAiVerbosity] = useState("2");
    const [savingMyAi, setSavingMyAi] = useState(false);
    const [myAiSaved, setMyAiSaved] = useState(false);

    // Per-user email settings (accessible to all roles)
    const [myEmail, setMyEmail] = useState<Record<string, string>>({
        SMTP_HOST: "", SMTP_PORT: "", SMTP_SECURITY: "ssl", SMTP_USERNAME: "", SMTP_PASSWORD: "", SMTP_FROM_EMAIL: "",
        IMAP_SERVER: "", IMAP_PORT: "", IMAP_SECURITY: "ssl", IMAP_USERNAME: "", IMAP_PASSWORD: "",
    });
    const [savingMyEmail, setSavingMyEmail] = useState(false);
    const [myEmailSaved, setMyEmailSaved] = useState(false);
    const [syncingInbox, setSyncingInbox] = useState(false);
    const [syncResult, setSyncResult] = useState<string | null>(null);

    useEffect(() => {
        const fetchSettingsAndKeys = async () => {
            if (!token) {
                setLoading(false);
                return;
            }

            try {
                const [settingsRes, keysRes, myEmailRes, myAiRes] = await Promise.all([
                    fetch(`${CRM_BASE}/company-settings`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`${CRM_BASE}/company-integrations`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`${CRM_BASE}/me/email-settings`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`${CRM_BASE}/me/settings`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                ]);

                if (settingsRes.status === 401 || keysRes.status === 401) {
                    sessionTimeout();
                    return;
                }

                if (settingsRes.ok) {
                    const data = await settingsRes.json() as Record<string, string>;
                    setSystemInstruction(readSettingValue(data, COMPANY_SETTING_KEYS.systemInstruction, ""));
                    setSttProvider(readSettingValue(data, COMPANY_SETTING_KEYS.sttProvider, "deepgram"));
                    setLlmProvider(readSettingValue(data, COMPANY_SETTING_KEYS.llmProvider, "mistral"));
                    setTtsProvider(readSettingValue(data, COMPANY_SETTING_KEYS.ttsProvider, "cartesia"));
                    setTelephonyEngine(readSettingValue(data, COMPANY_SETTING_KEYS.telephonyEngine, "twilio"));
                    setAiVerbosity(readSettingValue(data, COMPANY_SETTING_KEYS.aiVerbosity, "2"));
                    if (data.COMPETITOR_NAMES) setCompetitorNames(data.COMPETITOR_NAMES);
                }

                // Load competitor summary (mentions + counter-scripts)
                if (hasAdminAccess) {
                    try {
                        const summaryRes = await fetch(`${CRM_BASE}/competitors/summary`, {
                            headers: { "Authorization": `Bearer ${token}` }
                        });
                        if (summaryRes.ok) {
                            const summary = await summaryRes.json() as Array<{ competitor: string; count: number; counter_script?: string }>;
                            setCompetitorSummary(summary);
                            const scripts: Record<string, string> = {};
                            summary.forEach(s => { if (s.counter_script) scripts[s.competitor] = s.counter_script; });
                            setCounterScripts(scripts);
                        }
                    } catch {  }
                }

                if (myEmailRes.ok) {
                    const myEmailData = await myEmailRes.json() as Record<string, string>;
                    setMyEmail(prev => ({ ...prev, ...myEmailData }));
                }

                if (myAiRes.ok) {
                    const myAiData = await myAiRes.json() as Record<string, string>;
                    if (myAiData.SYSTEM_PROMPT) setMyAiPrompt(myAiData.SYSTEM_PROMPT);
                    if (myAiData.AI_VERBOSITY) setMyAiVerbosity(myAiData.AI_VERBOSITY);
                }

                if (keysRes.ok) {
                    const keysData = normalizeIntegrationValues(await keysRes.json() as Record<string, string>);
                    const defaultKeys = {
                        DEEPGRAM_API_KEY: "",
                        ELEVENLABS_API_KEY: "",
                        CARTESIA_API_KEY: "",
                        SARVAM_API_KEY: "",
                        SARVAM_STT_MODEL: "",
                        SARVAM_TTS_MODEL: "",
                        SARVAM_VOICE_ID: "",
                        CARTESIA_STT_MODEL: "",
                        CARTESIA_TTS_MODEL: "",
                        OPENAI_API_KEY: "",
                        MISTRAL_API_KEY: "",
                        ANTHROPIC_API_KEY: "",
                        GEMINI_API_KEY: "",
                        PERPLEXITY_API_KEY: "",
                        CEREBRAS_API_KEY: "",
                        OPENROUTER_API_KEY: "",
                        APOLLO_API_KEY: "",
                        TWILIO_ACCOUNT_SID: "",
                        TWILIO_AUTH_TOKEN: "",
                        PHONE_NUMBER_FROM: "",
                        WHATSAPP_NUMBER_FROM: "",
                        EXOTEL_ACCOUNT_SID: "",
                        EXOTEL_API_KEY: "",
                        EXOTEL_API_TOKEN: "",
                        EXOPHONE: "",
                        EXOTEL_APP_ID: "",
                        ENABLEX_APP_ID: "",
                        ENABLEX_APP_KEY: "",
                        ENABLEX_FROM_NUMBER: "",
                        SMTP_SERVER: "",
                        SMTP_PORT: "",
                        SMTP_USERNAME: "",
                        SMTP_PASSWORD: "",
                        SMTP_FROM_EMAIL: "",
                        ELEVENLABS_VOICE_ID: "",
                        CARTESIA_VOICE_ID: "",
                        DEEPGRAM_VOICE: "",
                        MISTRAL_MODEL: "",
                        OPENAI_MODEL: "",
                        GEMINI_MODEL: "",
                        ANTHROPIC_MODEL: "",
                        PERPLEXITY_MODEL: "",
                        OPENROUTER_MODEL: "",
                        CEREBRAS_MODEL: "",
                        DEEPGRAM_STT_MODEL: "",
                        DEEPGRAM_TTS_MODEL: "",
                        ELEVENLABS_TTS_MODEL: "",
                        ELEVENLABS_STT_MODEL: "",
                        MIMO_VOICE_ID: "",
                        MIMO_TTS_MODEL: "",
                        MIMO_API_KEY: "",
                        MIMO_MODEL: "",
                        SMALLEST_API_KEY: "",
                        SMALLEST_STT_MODEL: "",
                        SMALLEST_TTS_MODEL: "",
                        MISTRAL_TTS_MODEL: "",
                        MISTRAL_VOICE_ID: "",
                    };
                    setApiKeys({ ...defaultKeys, ...keysData });
                }
            } catch (error) {
                console.error("Error fetching settings:", error);
            } finally {
                setLoading(false);
            }
        };

        fetchSettingsAndKeys();
    }, [token, sessionTimeout]);

    useEffect(() => {
        if (!token || !hasAdminAccess) return;
        const controller = new AbortController();

        const fetchRoles = async () => {
            try {
                const res = await fetch(`${API_BASE}/admin/roles`, {
                    headers: { Authorization: `Bearer ${token}` },
                    signal: controller.signal,
                });
                if (res.status === 401) { sessionTimeout(); return; }
                if (!res.ok) {
                    console.warn("Failed to load roles", res.status);
                    return;
                }
                const data: RoleOption[] = await res.json();
                setRoles(data);
                if (!inviteRoleId && data.length) {
                    setInviteRoleId(data[0].id);
                }
            } catch (err) {
                if ((err as DOMException).name === "AbortError") {
                    return;
                }
                console.error("Failed to load roles", err);
            }
        };

        fetchRoles();
        return () => controller.abort();
    }, [token, hasAdminAccess, inviteRoleId]);


    const handleSave = async () => {
        console.log("💾 [Settings] Starting save operation...");
        setSaving(true);
        setSaveSuccess(false);

        try {
            const settingsPayload = {
                items: [
                    { key: "SYSTEM_INSTRUCTION", value: systemInstruction, is_secret: false },
                    { key: "STT_PROVIDER", value: sttProvider, is_secret: false },
                    { key: "LLM_PROVIDER", value: llmProvider, is_secret: false },
                    { key: "TTS_PROVIDER", value: ttsProvider, is_secret: false },
                    { key: "TELEPHONY_ENGINE", value: telephonyEngine, is_secret: false },
                    { key: "AI_VERBOSITY", value: aiVerbosity, is_secret: false },
                ],
            };

              const normalizedIntegrationValues = Object.entries(apiKeys).reduce<Record<string, string>>((acc, [rawKey, rawValue]) => {
                  const normalizedKey = INTEGRATION_KEY_ALIASES[rawKey] ?? rawKey;
                  acc[normalizedKey] = rawValue;
                  return acc;
              }, {});

              const integrationValues = { ...normalizedIntegrationValues };
              if (integrationValues.SARVAM_STT_MODEL && !integrationValues.SMALLEST_STT_MODEL) {
                  integrationValues.SMALLEST_STT_MODEL = integrationValues.SARVAM_STT_MODEL;
              }
              if (integrationValues.SARVAM_VOICE_ID && !integrationValues.SMALLEST_VOICE_ID) {
                  integrationValues.SMALLEST_VOICE_ID = integrationValues.SARVAM_VOICE_ID;
              }

              const integrationPayload = {
                  items: Object.entries(integrationValues)
                      .filter(([, value]) => typeof value === "string")
                      .map(([key, value]) => ({
                          key,
                          value: value.trim(),
                          is_secret: isSecretIntegrationKey(key),
                      }))
                      .filter((item) => item.value && !isMaskedValue(item.value)),
              };

            const [res, keysRes] = await Promise.all([
                fetch(`${CRM_BASE}/company-settings`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${token}`
                    },
                    body: JSON.stringify(settingsPayload),
                }),
                fetch(`${CRM_BASE}/company-integrations`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${token}`
                    },
                    body: JSON.stringify(integrationPayload),
                }),
            ]);

            if (res.status === 401 || keysRes.status === 401) {
                sessionTimeout();
                return;
            }

            if (!res.ok || !keysRes.ok) {
                throw new Error(`Save failed (${res.status}/${keysRes.status})`);
            }

            setSaveSuccess(true);
            setTimeout(() => setSaveSuccess(false), 3000);
        } catch (error) {
            console.error("❌ [Settings] Error saving settings:", error);
        } finally {
            setSaving(false);
        }
    };

    const handleSendInvite = async () => {
        if (!inviteEmail.trim()) {
            setInviteMessage("Please enter the invitee's email address.");
            return;
        }
        const roleId = inviteRoleId ?? roles[0]?.id;
        if (!roleId) {
            setInviteMessage("No roles available for invitations.");
            return;
        }

        setIsInviting(true);
        setInviteMessage(null);
        try {
            const res = await fetch(`${API_BASE}/auth/invites`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                    email: inviteEmail.trim(),
                    role_id: roleId,
                    expires_in_hours: inviteExpiresHours,
                }),
            });

            if (res.status === 401) { sessionTimeout(); return; }
            const data = await res.json();
            if (res.ok) {
                setInviteMessage(`Invite sent to ${inviteEmail.trim()}.`);
                setInviteEmail("");
            } else {
                setInviteMessage(data.detail || "Failed to send invite.");
            }
        } catch (err) {
            setInviteMessage("Network error while sending invite.");
        } finally {
            setIsInviting(false);
        }
    };

    const handleKeyChange = (key: string, value: string) => {
        setApiKeys(prev => ({ ...prev, [key]: value }));
    };

    const toggleKeyVisibility = (key: string) => {
        setVisibleKeys(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const saveMyAiSettings = async () => {
        if (!token) return;
        setSavingMyAi(true);
        try {
            await fetch(`${CRM_BASE}/me/settings`, {
                method: "PUT",
                headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ SYSTEM_PROMPT: myAiPrompt, AI_VERBOSITY: myAiVerbosity }),
            });
            setMyAiSaved(true);
            setTimeout(() => setMyAiSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save AI settings", e);
        } finally {
            setSavingMyAi(false);
        }
    };

    const handleMyEmailChange = (key: string, value: string) => {
        setMyEmail(prev => ({ ...prev, [key]: value }));
    };

    const saveMyEmailSettings = async () => {
        if (!token) return;
        setSavingMyEmail(true);
        try {
            await fetch(`${CRM_BASE}/me/email-settings`, {
                method: "PUT",
                headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify(myEmail),
            });
            setMyEmailSaved(true);
            setTimeout(() => setMyEmailSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save email settings", e);
        } finally {
            setSavingMyEmail(false);
        }
    };

    const saveCompetitorNames = async (overrideValue?: string) => {
        if (!token) return;
        setSavingCompetitors(true);
        try {
            await fetch(`${CRM_BASE}/company-settings`, {
                method: "PATCH",
                headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ items: [{ key: "COMPETITOR_NAMES", value: overrideValue ?? competitorNames, is_secret: false }] }),
            });
            setCompetitorSaved(true);
            setTimeout(() => setCompetitorSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save competitor names", e);
        } finally {
            setSavingCompetitors(false);
        }
    };

    const saveCounterScript = async (competitor: string) => {
        if (!token) return;
        setSavingScript(competitor);
        try {
            await fetch(`${CRM_BASE}/competitors/counter-script`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ competitor_name: competitor, counter_script: counterScripts[competitor] || "" }),
            });
            // Refresh summary so textarea falls back to the saved DB value
            const res = await fetch(`${CRM_BASE}/competitors/summary`, { headers: { "Authorization": `Bearer ${token}` } });
            if (res.ok) setCompetitorSummary(await res.json());
            // Clear the local edit — no longer "unsaved"
            setCounterScripts(prev => {
                const next = { ...prev };
                delete next[competitor];
                return next;
            });
        } catch (e) {
            console.error("Failed to save counter-script", e);
        } finally {
            setSavingScript(null);
        }
    };

    const addCompetitorToList = () => {
        const name = newCompetitorName.trim().toLowerCase();
        if (!name) return;
        const current = competitorNames.split(",").map(s => s.trim()).filter(Boolean);
        if (!current.includes(name)) {
            setCompetitorNames([...current, name].join(", "));
        }
        setNewCompetitorName("");
    };

    const removeCompetitorFromList = (name: string) => {
        const updated = competitorNames.split(",").map(s => s.trim()).filter(s => s && s !== name);
        setCompetitorNames(updated.join(", "));
    };

    const triggerInboxSync = async () => {
        if (!token) return;
        setSyncingInbox(true);
        setSyncResult(null);
        try {
            const res = await fetch(`${CRM_BASE}/email/sync`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${token}` },
            });
            const data = await res.json();
            setSyncResult(`Synced — ${data.emails_ingested ?? 0} new email(s) ingested`);
        } catch (e) {
            setSyncResult("Sync failed");
        } finally {
            setSyncingInbox(false);
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

            {hasAdminAccess && (
                <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-4 animate-in fade-in duration-300">
                    <div className="flex items-center justify-between">
                        <div>
                            <h2 className="text-lg font-bold text-slate-900 dark:text-white">Invite a teammate</h2>
                            <p className="text-sm text-slate-500 dark:text-slate-400">
                                Send an invitation link that expires in a few days.
                            </p>
                        </div>
                        <span className="text-xs uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">
                            Owner Only
                        </span>
                    </div>
                    <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_1fr] items-end">
                        <div>
                            <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Email</label>
                            <input
                                type="email"
                                value={inviteEmail}
                                onChange={(e) => setInviteEmail(e.target.value)}
                                placeholder="jane@company.com"
                                className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                            />
                        </div>
                        <div>
                            <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Role</label>
                            <select
                                value={inviteRoleId ?? ""}
                                onChange={(e) => setInviteRoleId(Number(e.target.value))}
                                className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                            >
                                {roles.length === 0 && <option value="">Loading roles...</option>}
                                {roles.map((role) => (
                                    <option key={role.id} value={role.id}>
                                        {role.name.replace(/_/g, " ")}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Expires (hours)</label>
                            <input
                                type="number"
                                min={1}
                                max={168}
                                value={inviteExpiresHours}
                                onChange={(e) => setInviteExpiresHours(Number(e.target.value))}
                                className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                            />
                        </div>
                        <button
                            type="button"
                            onClick={handleSendInvite}
                            disabled={isInviting}
                            className="w-full rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white font-semibold py-2 text-sm uppercase tracking-wide shadow-lg shadow-emerald-500/30 hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isInviting ? "Sending..." : "Send Invite"}
                        </button>
                    </div>
                    {inviteMessage && (
                        <p className={`text-xs ${inviteMessage.includes("sent") ? "text-emerald-500" : "text-red-500"}`}>
                            {inviteMessage}
                        </p>
                    )}
                </div>
            )}

            {/* Tabs */}
            <div className="flex space-x-2 border-b border-slate-200 dark:border-slate-800 pb-2">
                {[
                    { id: "general", label: "General & Appearance", icon: Settings },
                    { id: "myemail", label: "My Email", icon: Mail },
                    ...(hasAdminAccess ? [
                        { id: "persona", label: "Voice & AI Engine", icon: Brain },
                        { id: "keys", label: "Integration Keys", icon: KeyRound },
                        { id: "competitors", label: "Competitors", icon: Zap },
                    ] : []),
                ].map((tab) => {
                    const Icon = tab.icon;
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex items-center space-x-2 px-4 py-2 rounded-xl font-bold transition-all ${
                                activeTab === tab.id 
                                ? "bg-violet-600 text-white shadow-md" 
                                : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                            }`}
                        >
                            <Icon className="h-4 w-4" />
                            <span>{tab.label}</span>
                        </button>
                    )
                })}
            </div>

            <div className="space-y-6">
                {/* General Tab */}
                {activeTab === "general" && (
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

                {/* My Rio — visible to all roles */}
                <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center space-x-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-purple-600">
                                <Brain className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">My Rio Persona</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">
                                    {hasAdminAccess ? "Your personal override — takes priority over company-wide prompt" : "Customize Rio's voice for your calls"}
                                </p>
                            </div>
                        </div>
                        <div className="flex items-center space-x-2">
                            {myAiSaved && (
                                <span className="flex items-center space-x-1 text-emerald-600 text-sm font-bold">
                                    <CheckCircle2 className="h-4 w-4" /><span>Saved</span>
                                </span>
                            )}
                            <button
                                onClick={saveMyAiSettings}
                                disabled={savingMyAi}
                                className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-violet-600 text-white font-bold hover:bg-violet-700 disabled:opacity-50 transition-all text-sm"
                            >
                                {savingMyAi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                <span>Save</span>
                            </button>
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div>
                            <label className="text-xs font-bold uppercase text-slate-500 mb-1 block">
                                Response Brevity (1 = very brief · 5 = detailed)
                            </label>
                            <div className="flex items-center space-x-4">
                                <input
                                    type="range" min="1" max="5" step="1"
                                    value={myAiVerbosity}
                                    onChange={(e) => setMyAiVerbosity(e.target.value)}
                                    className="flex-1 accent-violet-600"
                                />
                                <span className="w-6 text-center font-bold text-violet-600">{myAiVerbosity}</span>
                            </div>
                        </div>
                        <div>
                            <label className="text-xs font-bold uppercase text-slate-500 mb-1 block">Personal Prompt / Persona Script</label>
                            <textarea
                                rows={6}
                                value={myAiPrompt}
                                onChange={(e) => setMyAiPrompt(e.target.value)}
                                placeholder="E.g. You are Rio, a friendly sales representative for Yexis Electronics. Always greet the lead by name and focus on their specific needs..."
                                className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                            />
                            <p className="mt-1 text-xs text-slate-400">Leave blank to use the company-wide Rio prompt.</p>
                        </div>
                    </div>
                </div>

                {/* Telephony Configuration */}
                {hasAdminAccess && (
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
                    </div>
                )}

                {/* AI Configuration Tab */}
                {activeTab === "persona" && hasAdminAccess && (
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
                                        <option value="deepgram">Deepgram</option>
                                        <option value="sarvam">Sarvam</option>
                                        <option value="cartesia">Cartesia</option>
                                        <option value="elevenlabs">ElevenLabs</option>
                                        <option value="smallest">Smallest</option>
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
                                        <option value="mistral">Mistral</option>
                                        <option value="anthropic">Claude</option>
                                        <option value="google">Gemini</option>
                                        <option value="perplexity">Perplexity</option>
                                        <option value="openrouter">OpenRouter (Inference)</option>
                                        <option value="cerebras">Cerebras (Inference)</option>
                                        <option value="sarvam">Sarvam (Multilingual)</option>
                                        <option value="mimo">Mimo</option>
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
                                        <option value="cartesia">Cartesia</option>
                                        <option value="elevenlabs">ElevenLabs</option>
                                        <option value="sarvam">Sarvam</option>
                                        <option value="deepgram">Deepgram</option>
                                        <option value="mimo">Mimo</option>
                                        <option value="mistral">Mistral</option>
                                        <option value="smallest">Smallest</option>
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


                {/* Integrations Keys Tab */}
                {/* My Email Tab — visible to all roles */}
                {activeTab === "myemail" && (
                    <div className="space-y-6">
                        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                            <div className="flex items-center justify-between mb-6">
                                <div className="flex items-center space-x-3">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500">
                                        <Mail className="h-5 w-5 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">My Email Settings</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">
                                            Personal credentials — override company defaults for emails sent by you
                                        </p>
                                    </div>
                                </div>
                                <div className="flex items-center space-x-2">
                                    {myEmailSaved && (
                                        <span className="flex items-center space-x-1 text-emerald-600 text-sm font-bold">
                                            <CheckCircle2 className="h-4 w-4" />
                                            <span>Saved</span>
                                        </span>
                                    )}
                                    <button
                                        onClick={saveMyEmailSettings}
                                        disabled={savingMyEmail}
                                        className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-violet-600 text-white font-bold hover:bg-violet-700 disabled:opacity-50 transition-all"
                                    >
                                        {savingMyEmail ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                        <span>Save</span>
                                    </button>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                {/* Outbound SMTP */}
                                <div className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">Outbound (SMTP)</h4>
                                    {[
                                        { key: "SMTP_HOST", label: "SMTP Server", placeholder: "mail.example.com", secret: false },
                                        { key: "SMTP_PORT", label: "SMTP Port", placeholder: "465 (SSL) · 587 (STARTTLS)", secret: false },
                                        { key: "SMTP_USERNAME", label: "Username / Login", placeholder: "you@example.com", secret: true },
                                        { key: "SMTP_PASSWORD", label: "Password", placeholder: "••••••••", secret: true },
                                        { key: "SMTP_FROM_EMAIL", label: "From Email", placeholder: "you@example.com", secret: false },
                                    ].map(({ key, label, placeholder, secret }) => (
                                        <div key={key} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{label}</label>
                                            <div className="relative">
                                                <input
                                                    type={secret && !visibleKeys[`me_${key}`] ? "password" : "text"}
                                                    placeholder={placeholder}
                                                    value={myEmail[key] || ""}
                                                    onChange={(e) => handleMyEmailChange(key, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(myEmail[key]).startsWith("***")) handleMyEmailChange(key, "");
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 font-mono text-sm"
                                                />
                                                {secret && (
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleKeyVisibility(`me_${key}`)}
                                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                                                    >
                                                        {visibleKeys[`me_${key}`] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-slate-500 uppercase">Security</label>
                                        <select
                                            value={myEmail["SMTP_SECURITY"] || "ssl"}
                                            onChange={(e) => handleMyEmailChange("SMTP_SECURITY", e.target.value)}
                                            className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                                        >
                                            <option value="ssl">SSL / TLS (port 465)</option>
                                            <option value="starttls">STARTTLS (port 587)</option>
                                            <option value="none">None / Plain (port 25)</option>
                                        </select>
                                    </div>
                                </div>

                                {/* Inbound IMAP */}
                                <div className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">Inbound (IMAP)</h4>
                                    <p className="text-xs text-slate-500">Replies to emails sent by you will be pulled from this inbox every 3 minutes.</p>
                                    {[
                                        { key: "IMAP_SERVER", label: "IMAP Server", placeholder: "mail.example.com", secret: false },
                                        { key: "IMAP_PORT", label: "IMAP Port", placeholder: "993 (SSL) · 143 (STARTTLS)", secret: false },
                                        { key: "IMAP_USERNAME", label: "Username / Login", placeholder: "you@example.com", secret: true },
                                        { key: "IMAP_PASSWORD", label: "Password", placeholder: "••••••••", secret: true },
                                    ].map(({ key, label, placeholder, secret }) => (
                                        <div key={key} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{label}</label>
                                            <div className="relative">
                                                <input
                                                    type={secret && !visibleKeys[`me_${key}`] ? "password" : "text"}
                                                    placeholder={placeholder}
                                                    value={myEmail[key] || ""}
                                                    onChange={(e) => handleMyEmailChange(key, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(myEmail[key]).startsWith("***")) handleMyEmailChange(key, "");
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 font-mono text-sm"
                                                />
                                                {secret && (
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleKeyVisibility(`me_${key}`)}
                                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                                                    >
                                                        {visibleKeys[`me_${key}`] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-slate-500 uppercase">Security</label>
                                        <select
                                            value={myEmail["IMAP_SECURITY"] || "ssl"}
                                            onChange={(e) => handleMyEmailChange("IMAP_SECURITY", e.target.value)}
                                            className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                                        >
                                            <option value="ssl">SSL / TLS (port 993)</option>
                                            <option value="starttls">STARTTLS (port 143)</option>
                                            <option value="none">None / Plain</option>
                                        </select>
                                    </div>

                                    <div className="pt-2 border-t border-slate-200 dark:border-slate-700">
                                        <button
                                            onClick={triggerInboxSync}
                                            disabled={syncingInbox}
                                            className="flex items-center space-x-2 px-4 py-2 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-all text-sm"
                                        >
                                            {syncingInbox ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                            <span>Sync Inbox Now</span>
                                        </button>
                                        {syncResult && (
                                            <p className="mt-2 text-xs text-slate-500">{syncResult}</p>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
                                Leave blank to use company-wide email settings. Your password is stored encrypted.
                            </p>
                        </div>
                    </div>
                )}

                {activeTab === "keys" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-green-400 to-emerald-600">
                                <KeyRound className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">API Credentials</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Securely store your provider keys in the encrypted database</p>
                            </div>
                        </div>

                        <div className="grid gap-6 md:grid-cols-2">
                            {Object.entries({
                                "Twilio & Messaging": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM"],
                                "Exotel (Telephony)": ["EXOTEL_ACCOUNT_SID", "EXOTEL_API_KEY", "EXOTEL_API_TOKEN", "EXOPHONE", "EXOTEL_APP_ID"],
                                "EnableX (Telephony)": ["ENABLEX_APP_ID", "ENABLEX_APP_KEY", "ENABLEX_FROM_NUMBER"],
                                "Speech-to-Text (STT)": ["DEEPGRAM_API_KEY", "SARVAM_API_KEY", "DEEPGRAM_STT_MODEL", "CARTESIA_STT_MODEL", "SARVAM_STT_MODEL", "ELEVENLABS_STT_MODEL", "DEEPGRAM_VOICE", "SMALLEST_STT_MODEL", "SMALLEST_VOICE_ID"],
                                "Text-to-Speech (TTS)": ["CARTESIA_API_KEY", "ELEVENLABS_API_KEY", "MIMO_API_KEY", "CARTESIA_VOICE_ID", "ELEVENLABS_VOICE_ID", "MIMO_VOICE_ID", "SARVAM_VOICE_ID", "DEEPGRAM_TTS_MODEL", "ELEVENLABS_TTS_MODEL", "MIMO_TTS_MODEL", "SARVAM_TTS_MODEL", "CARTESIA_TTS_MODEL", "MISTRAL_TTS_MODEL", "SMALLEST_API_KEY", "SMALLEST_TTS_MODEL", "MISTRAL_VOICE_ID"],
                                "Intelligence (LLM)": ["OPENAI_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "MIMO_API_KEY", "MISTRAL_MODEL", "OPENAI_MODEL", "GEMINI_MODEL", "ANTHROPIC_MODEL", "PERPLEXITY_MODEL", "OPENROUTER_MODEL", "CEREBRAS_MODEL", "MIMO_MODEL", "SARVAM_MODEL"],
                                "Email (SMTP — Outbound)": ["SMTP_SERVER", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
                                "Email (IMAP — Inbound)": ["IMAP_SERVER", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD"],
                                "Enrichment": ["APOLLO_API_KEY", "LUSHA_API_KEY", "ZOOMINFO_CLIENT_ID", "ZOOMINFO_API_KEY"]
                            }).map(([groupName, keys]) => (
                                <div key={groupName} className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">{groupName}</h4>
                                    
                                    {keys.map((keyName) => (
                                        <div key={keyName} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{keyName.replace(/_/g, " ")}</label>
                                            <div className="relative group/key">
                                                <input
                                                    type={visibleKeys[keyName] || String(apiKeys[keyName]).startsWith("***") ? "text" : "password"}
                                                    placeholder="sk-..."
                                                    value={apiKeys[keyName] || ""}
                                                    onChange={(e) => handleKeyChange(keyName, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(apiKeys[keyName]).indexOf("*") !== -1) {
                                                            handleKeyChange(keyName, "");
                                                        }
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-500 font-mono text-sm"
                                                />
                                                <button
                                                    type="button"
                                                    onClick={() => toggleKeyVisibility(keyName)}
                                                    className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-violet-500 transition-colors"
                                                    title={visibleKeys[keyName] ? "Hide Key" : "Show Key"}
                                                >
                                                    {visibleKeys[keyName] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Competitors Tab */}
                {activeTab === "competitors" && hasAdminAccess && (() => {
                    // Unified row list: union of tracked names (COMPETITOR_NAMES setting)
                    // and DB rows (competitorSummary). This means:
                    //  - Adding a name shows it immediately as a row before any call detects it
                    //  - Competitors detected on calls also appear even if not in the tracked list
                    const parsedNames = competitorNames.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
                    const summaryMap = Object.fromEntries(competitorSummary.map(s => [s.competitor, s]));
                    const allNames = [...new Set([...parsedNames, ...Object.keys(summaryMap)])];
                    const rows = allNames.map(name => ({
                        competitor: name,
                        count: summaryMap[name]?.count ?? 0,
                        inTrackedList: parsedNames.includes(name),
                    }));

                    return (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
                        {/* Header */}
                        <div className="flex items-center space-x-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-400 to-red-500">
                                <Zap className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Competitor Intelligence</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">
                                    Rio detects these names live on calls. When detected, the counter-script is injected into the AI context automatically.
                                </p>
                            </div>
                        </div>

                        {/* Add competitor row */}
                        <div className="flex gap-2">
                            <input
                                type="text"
                                placeholder="Competitor name, e.g. salesforce"
                                value={newCompetitorName}
                                onChange={e => setNewCompetitorName(e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter") addCompetitorToList(); }}
                                className="flex-1 p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                            />
                            <button
                                onClick={addCompetitorToList}
                                className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors whitespace-nowrap"
                            >
                                + Add
                            </button>
                        </div>

                        {/* Unified table: one row per competitor */}
                        {rows.length === 0 ? (
                            <div className="text-center py-10 text-slate-400 text-sm">
                                No competitors tracked yet. Type a name above and click Add.
                                <br />
                                <span className="text-xs mt-1 block">If left empty, Rio uses built-in defaults: salesforce, hubspot, zoho, pipedrive…</span>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {rows.map(row => (
                                    <div key={row.competitor} className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 overflow-hidden">
                                        {/* Row header */}
                                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                                            <div className="flex items-center gap-3">
                                                <span className="font-semibold capitalize text-slate-800 dark:text-slate-200">{row.competitor}</span>
                                                {row.count > 0 && (
                                                    <span className="px-2 py-0.5 rounded-full bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 text-xs font-bold">
                                                        {row.count} mention{row.count !== 1 ? "s" : ""}
                                                    </span>
                                                )}
                                                {row.inTrackedList ? (
                                                    <span className="px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs">tracked</span>
                                                ) : (
                                                    <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 text-xs">detected on call</span>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-2">
                                                {!row.inTrackedList && (
                                                    <button
                                                        onClick={() => {
                                                            const updated = [...parsedNames, row.competitor].join(", ");
                                                            setCompetitorNames(updated);
                                                            saveCompetitorNames(updated);
                                                        }}
                                                        className="text-xs px-2 py-1 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 hover:bg-violet-200 transition-colors"
                                                    >
                                                        + Track
                                                    </button>
                                                )}
                                                {row.inTrackedList && (
                                                    <button
                                                        onClick={() => removeCompetitorFromList(row.competitor)}
                                                        className="text-xs px-2 py-1 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 transition-colors"
                                                    >
                                                        Remove
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        {/* Counter-script input */}
                                        <div className="px-4 py-3 space-y-2">
                                            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Counter-Script (injected into AI when detected)</label>
                                            <textarea
                                                rows={2}
                                                placeholder={`What should Rio say when ${row.competitor} comes up? e.g. "We offer similar features at 30% less cost, and we integrate with your current stack…"`}
                                                value={counterScripts[row.competitor] ?? summaryMap[row.competitor]?.counter_script ?? ""}
                                                onChange={e => setCounterScripts(prev => ({ ...prev, [row.competitor]: e.target.value }))}
                                                className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm resize-none"
                                            />
                                            <div className="flex items-center gap-3">
                                                <button
                                                    onClick={() => saveCounterScript(row.competitor)}
                                                    disabled={savingScript === row.competitor}
                                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors disabled:opacity-50"
                                                >
                                                    {savingScript === row.competitor ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                                                    Save Script
                                                </button>
                                                {savingScript === null && counterScripts[row.competitor] !== undefined && (
                                                    <span className="text-xs text-slate-400">unsaved changes</span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Save tracked list footer */}
                        <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-slate-700">
                            <p className="text-xs text-slate-400">
                                {parsedNames.length > 0
                                    ? `${parsedNames.length} competitor${parsedNames.length !== 1 ? "s" : ""} in your tracked list`
                                    : "Using built-in defaults"}
                            </p>
                            <div className="flex items-center gap-3">
                                {competitorSaved && <span className="text-xs text-green-600 font-medium flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Saved</span>}
                                <button
                                    onClick={() => saveCompetitorNames()}
                                    disabled={savingCompetitors}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
                                >
                                    {savingCompetitors ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                    Save Tracked List
                                </button>
                            </div>
                        </div>
                    </div>
                    );
                })()}

                {/* Save Button */}
                {hasAdminAccess && (
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
