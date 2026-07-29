"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  CheckCircle2, Loader2, ExternalLink, Unplug, Plug, XCircle, Settings, Zap, Users, BarChart3, Search, Mail,
  Plus, RefreshCw, Trash2, Play, Network, ChevronDown, ChevronUp, 
} from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { useMCPServers, useCreateMCPServer, useDeleteMCPServer, useDiscoverMCPTools, usePingMCPHealth } from "@/hooks/useMCPServers";
import type { MCPServerRecord } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

// ─── types ────────────────────────────────────────────────────────────────────

type ConnectionStatus = "idle" | "checking" | "connected" | "disconnected" | "connecting" | "error";

type SessionTimeout = () => void;

type ConnectorDef = {
  id: string;
  name: string;
  tagline: string;
  icon: React.ReactNode;
  iconBg: string;
  authType?: "oauth" | "apikey";
  authUrl?: string;       // oauth only
  connectUrl?: string;    // apikey only — POST {api_key}
  statusUrl: string;
  disconnectUrl: string;
  capabilities: string[];
  docsUrl?: string;
  envVarsRequired: string[];
};

type MCPServer = MCPServerRecord;

// ─── connector definitions ────────────────────────────────────────────────────

const CONNECTORS: ConnectorDef[] = [
  {
    id: "zoho",
    name: "Zoho CRM",
    tagline: "Two-way sync of deals, contacts, and pipeline stages",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#E42527" />
        <text x="20" y="27" textAnchor="middle" fill="white" fontSize="14" fontWeight="bold" fontFamily="Arial">Z</text>
      </svg>
    ),
    iconBg: "bg-red-50 dark:bg-red-900/20",
    authUrl: `${API_BASE}/crm/zoho/auth-url`,
    statusUrl: `${API_BASE}/crm/zoho/status`,
    disconnectUrl: `${API_BASE}/crm/zoho/disconnect`,
    capabilities: [
      "Read & update Deals, Contacts, Leads",
      "Push AI call outcomes to pipeline stages",
      "Pull contact history before calls",
      "Sync won/lost outcomes automatically",
    ],
    envVarsRequired: ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET"],
    docsUrl: "https://api-console.zoho.com/",
  },
  {
    id: "apollo",
    name: "Apollo.io",
    tagline: "Lead enrichment, prospecting, and outreach sequencing",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#7C3AED" />
        <circle cx="20" cy="16" r="5" fill="white" fillOpacity="0.9" />
        <path d="M8 32 Q20 20 32 32" stroke="white" strokeWidth="2.5" strokeLinecap="round" fill="none" fillOpacity="0.7" />
      </svg>
    ),
    iconBg: "bg-violet-50 dark:bg-violet-900/20",
    authUrl: `${API_BASE}/crm/apollo/auth-url`,
    statusUrl: `${API_BASE}/crm/apollo/status`,
    disconnectUrl: `${API_BASE}/crm/apollo/disconnect`,
    capabilities: [
      "Search 275M+ verified contacts & companies",
      "Enrich leads with email, phone, firmographics",
      "Enroll contacts in outreach sequences",
      "Sync reply analytics back to Rio",
    ],
    envVarsRequired: ["APOLLO_CLIENT_ID", "APOLLO_CLIENT_SECRET"],
    docsUrl: "https://developer.apollo.io/",
  },
  {
    id: "hubspot",
    name: "HubSpot",
    tagline: "CRM sync — contacts, deals, companies, and pipeline stages",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#FF7A59" />
        <circle cx="26" cy="14" r="4" fill="white" fillOpacity="0.95" />
        <circle cx="26" cy="14" r="1.5" fill="#FF7A59" />
        <line x1="22.5" y1="14" x2="14" y2="20" stroke="white" strokeWidth="2" strokeLinecap="round" />
        <line x1="22.5" y1="14" x2="14" y2="26" stroke="white" strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="20" r="3" fill="white" fillOpacity="0.9" />
        <circle cx="12" cy="26" r="3" fill="white" fillOpacity="0.9" />
      </svg>
    ),
    iconBg: "bg-orange-50 dark:bg-orange-900/20",
    authUrl: `${API_BASE}/crm/hubspot/auth-url`,
    statusUrl: `${API_BASE}/crm/hubspot/status`,
    disconnectUrl: `${API_BASE}/crm/hubspot/disconnect`,
    capabilities: [
      "Read Contacts, Deals, Companies & Owners",
      "Pull contact & deal history before calls",
      "Look up deal pipeline stages during calls",
      "Read company firmographics for enrichment",
    ],
    envVarsRequired: ["HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"],
    docsUrl: "https://developers.hubspot.com/",
  },
  {
    id: "linkedin",
    name: "LinkedIn Sales Navigator",
    tagline: "Prospect smarter with AI-powered lead recommendations",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#0A66C2" />
        <text x="20" y="27" textAnchor="middle" fill="white" fontSize="18" fontWeight="bold" fontFamily="Arial">in</text>
      </svg>
    ),
    iconBg: "bg-blue-50 dark:bg-blue-900/20",
    authUrl: `${API_BASE}/crm/linkedin/auth-url`,
    statusUrl: `${API_BASE}/crm/linkedin/status`,
    disconnectUrl: `${API_BASE}/crm/linkedin/disconnect`,
    capabilities: [
      "AI-powered lead & account recommendations",
      "Search 900M+ LinkedIn profiles",
      "View buyer intent signals before calls",
      "Track relationship history & InMail activity",
    ],
    envVarsRequired: ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"],
    docsUrl: "https://developer.linkedin.com/",
  },
  {
    id: "salesforce",
    name: "Salesforce",
    tagline: "Enterprise CRM — contacts, opportunities, and pipeline sync",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#00A1E0" />
        <path
          d="M20 9c-2.5 0-4.7 1.3-6 3.3a5.5 5.5 0 0 0-7 5.3c0 3 2.5 5.5 5.5 5.5h14a5 5 0 0 0 0-10 5 5 0 0 0-.6 0A6 6 0 0 0 20 9z"
          fill="white"
          fillOpacity="0.95"
        />
      </svg>
    ),
    iconBg: "bg-sky-50 dark:bg-sky-900/20",
    authUrl: `${API_BASE}/crm/salesforce/auth-url`,
    statusUrl: `${API_BASE}/crm/salesforce/status`,
    disconnectUrl: `${API_BASE}/crm/salesforce/disconnect`,
    capabilities: [
      "Read & sync Contacts, Accounts, Opportunities",
      "Push AI call outcomes to opportunity stages",
      "Pull full CRM history before calls",
      "Works with any Salesforce org instance",
    ],
    envVarsRequired: ["SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"],
    docsUrl: "https://developer.salesforce.com/",
  },
  {
    id: "instantly",
    name: "Instantly",
    tagline: "Cold email sequencing and deliverability at scale",
    authType: "apikey",
    connectUrl: `${API_BASE}/crm/instantly/connect`,
    statusUrl: `${API_BASE}/crm/instantly/status`,
    disconnectUrl: `${API_BASE}/crm/instantly/disconnect`,
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#F59E0B" />
        <path d="M12 20 L20 10 L20 17 L28 17 L20 30 L20 23 Z" fill="white" fillOpacity="0.95" />
      </svg>
    ),
    iconBg: "bg-amber-50 dark:bg-amber-900/20",
    capabilities: [
      "Send AI-personalized cold email sequences",
      "Track open, click & reply rates",
      "Rotate sending accounts for deliverability",
      "Enrich & enroll leads automatically",
    ],
    envVarsRequired: [],
    docsUrl: "https://app.instantly.ai/app/settings/integrations",
  },
  {
    id: "google",
    name: "Google Workspace",
    tagline: "Calendar, Meet, Gmail, Drive, Sheets & Docs — one connection",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="white" />
        <path d="M20 8.5a11.5 11.5 0 1 0 0 23 11.5 11.5 0 0 0 0-23z" fill="#4285F4" />
        <path d="M28.8 20.2c0-.6-.1-1.2-.2-1.7H20v3.3h5c-.2 1.2-.9 2.2-1.8 2.8v2.4h3c1.7-1.6 2.6-3.9 2.6-6.8z" fill="#4285F4" />
        <path d="M20 31.5c2.6 0 4.8-.9 6.4-2.4l-3-2.4c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.2h-3.1v2.4a9.5 9.5 0 0 0 8.7 5.6z" fill="#34A853" />
        <path d="M14.4 23.5a5.7 5.7 0 0 1 0-3.6v-2.4h-3.1a9.5 9.5 0 0 0 0 8.4l3.1-2.4z" fill="#FBBC04" />
        <path d="M20 14.2c1.5 0 2.8.5 3.8 1.5l2.8-2.8A9.5 9.5 0 0 0 11.3 17l3.1 2.4c.8-2.4 3-4.2 5.6-4.2z" fill="#EA4335" />
      </svg>
    ),
    iconBg: "bg-white dark:bg-slate-800",
    authUrl: `${API_BASE}/crm/calendar/auth-url`,
    statusUrl: `${API_BASE}/crm/calendar/status`,
    disconnectUrl: `${API_BASE}/crm/calendar/disconnect`,
    capabilities: [
      "Book & manage Google Calendar meetings",
      "Create Google Meet video calls automatically",
      "Send & read emails via Gmail",
      "Read/write Google Drive files & Sheets",
      "Generate proposals in Google Docs",
    ],
    envVarsRequired: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
    docsUrl: "https://console.cloud.google.com/",
  },
  {
    id: "microsoft",
    name: "Microsoft 365",
    tagline: "Outlook email, OneDrive files, and Teams calendar — one connection",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="white" />
        <rect x="8" y="8" width="11" height="11" fill="#F25022" />
        <rect x="21" y="8" width="11" height="11" fill="#7FBA00" />
        <rect x="8" y="21" width="11" height="11" fill="#00A4EF" />
        <rect x="21" y="21" width="11" height="11" fill="#FFB900" />
      </svg>
    ),
    iconBg: "bg-slate-50 dark:bg-slate-800",
    authUrl: `${API_BASE}/crm/microsoft/auth-url`,
    statusUrl: `${API_BASE}/crm/microsoft/status`,
    disconnectUrl: `${API_BASE}/crm/microsoft/disconnect`,
    capabilities: [
      "Read & send emails via Outlook",
      "Access and upload OneDrive files",
      "Read & write Outlook Calendar events",
      "Works with personal & business Microsoft accounts",
    ],
    envVarsRequired: ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"],
    docsUrl: "https://portal.azure.com/",
  },
];

const COMING_SOON: { name: string; icon: React.ReactNode; iconBg: string; tagline: string }[] = [];

// ─── ConnectorCard ─────────────────────────────────────────────────────────────

function ConnectorCard({ connector, sessionTimeout }: { connector: ConnectorDef; sessionTimeout?: SessionTimeout }) {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [toast, setToast] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [showApiKeyInput, setShowApiKeyInput] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();

  const isApiKey = connector.authType === "apikey";

  const checkStatus = useCallback(async () => {
    setStatus("checking");
    try {
      const res = await apiFetch(connector.statusUrl);
      if (res.status === 401) { sessionTimeout?.(); return; }
      if (!res.ok) { setStatus("disconnected"); return; }
      const data = await res.json();
      setStatus(data.connected ? "connected" : "disconnected");
    } catch {
      setStatus("error");
    }
  }, [connector.statusUrl, sessionTimeout]);

  // Initial status check
  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  // Detect OAuth callback via URL param
  useEffect(() => {
    const param = searchParams.get(connector.id);
    if (param === "connected") {
      setStatus("connected");
      setToast(`${connector.name} connected successfully`);
      setTimeout(() => setToast(null), 4000);
      // Clean up URL param
      const url = new URL(window.location.href);
      url.searchParams.delete(connector.id);
      router.replace(url.pathname + (url.search || ""), { scroll: false });
    }
  }, [searchParams, connector.id, connector.name, router]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    let attempts = 0;
    pollRef.current = setInterval(async () => {
      attempts++;
      try {
        const res = await apiFetch(connector.statusUrl);
        if (res.status === 401) { sessionTimeout?.(); stopPolling(); return; }
        if (res.ok) {
          const data = await res.json();
          if (data.connected) {
            setStatus("connected");
            setToast(`${connector.name} connected successfully`);
            setTimeout(() => setToast(null), 4000);
            stopPolling();
            return;
          }
        }
      } catch { /* ignore */ }
      if (attempts >= 30) { // 60s max
        stopPolling();
        setStatus("disconnected");
      }
    }, 2000);
  }, [connector.statusUrl, connector.name, sessionTimeout, stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const handleConnectApiKey = async () => {
    if (!apiKeyInput.trim()) return;
    setStatus("connecting");
    try {
      const res = await apiFetch(connector.connectUrl!, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKeyInput.trim() }),
      });
      if (res.status === 401) { sessionTimeout?.(); setStatus("disconnected"); return; }
      if (!res.ok) {
        let detail = "Invalid API key";
        try { const body = await res.json(); detail = body.detail ?? detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      setStatus("connected");
      setToast(`${connector.name} connected successfully`);
      setShowApiKeyInput(false);
      setApiKeyInput("");
      setTimeout(() => setToast(null), 4000);
    } catch (err: unknown) {
      setStatus("disconnected");
      setToast(err instanceof Error ? err.message : "Connection failed");
      setTimeout(() => setToast(null), 5000);
    }
  };

  const handleConnect = async () => {
    if (isApiKey) { setShowApiKeyInput(true); setExpanded(true); return; }
    setStatus("connecting");
    try {
      const res = await apiFetch(connector.authUrl!);
      if (res.status === 401) { sessionTimeout?.(); return; }
      if (!res.ok) {
        let detail = "Failed to get auth URL";
        try { const body = await res.json(); detail = body.detail ?? detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      const { auth_url } = await res.json();

      // Try popup first; fall back to new tab
      const popup = window.open(auth_url, "oauth_popup", "width=600,height=700,left=400,top=100");
      if (!popup || popup.closed || typeof popup.closed === "undefined") {
        window.open(auth_url, "_blank");
      }
      startPolling();
    } catch (err: unknown) {
      setStatus("error");
      setToast(err instanceof Error ? err.message : "Connection failed");
      setTimeout(() => setToast(null), 4000);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm(`Disconnect ${connector.name}? Your AI agents will lose access to this integration.`)) return;
    try {
      const res = await apiFetch(connector.disconnectUrl, { method: "DELETE" });
      if (res.status === 401) { sessionTimeout?.(); return; }
      setStatus("disconnected");
      setToast(`${connector.name} disconnected`);
      setTimeout(() => setToast(null), 3000);
    } catch {
      setToast("Disconnect failed — try again");
      setTimeout(() => setToast(null), 3000);
    }
  };

  const isConnected = status === "connected";
  const isLoading = status === "checking" || status === "connecting";

  return (
    <div
      className={`relative rounded-2xl border transition-all duration-200 overflow-hidden ${
        isConnected
          ? "border-green-200 dark:border-green-800 bg-white dark:bg-slate-900 shadow-sm"
          : "border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900"
      }`}
    >
      {/* Connected accent bar */}
      {isConnected && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-green-400 to-emerald-500" />
      )}

      {/* Toast */}
      {toast && (
        <div className="absolute top-3 right-3 z-10 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-medium shadow-lg animate-fade-in">
          <CheckCircle2 className="h-3.5 w-3.5 text-green-400 dark:text-green-600" />
          {toast}
        </div>
      )}

      <div className="p-5">
        {/* Header row */}
        <div className="flex items-start gap-4">
          {/* Icon */}
          <div className={`flex-shrink-0 h-12 w-12 rounded-xl flex items-center justify-center ${connector.iconBg}`}>
            {connector.icon}
          </div>

          {/* Name + tagline */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">{connector.name}</h3>
              {/* Status badge */}
              {status === "checking" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-500">
                  <Loader2 className="h-3 w-3 animate-spin" /> Checking...
                </span>
              ) : isConnected ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                  Connected
                </span>
              ) : status === "connecting" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400">
                  <Loader2 className="h-3 w-3 animate-spin" /> Connecting...
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                  Not connected
                </span>
              )}
            </div>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400 leading-snug">{connector.tagline}</p>
          </div>

          {/* Action button */}
          <div className="flex-shrink-0 flex items-center gap-2">
            {isConnected ? (
              <button
                onClick={handleDisconnect}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:border-red-300 hover:text-red-600 dark:hover:text-red-400 dark:hover:border-red-800 transition-colors"
              >
                <Unplug className="h-3.5 w-3.5" />
                Disconnect
              </button>
            ) : (
              <button
                onClick={handleConnect}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-sm font-semibold bg-slate-900 dark:bg-white text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-100 disabled:opacity-50 transition-colors"
              >
                {isLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plug className="h-3.5 w-3.5" />
                )}
                {status === "connecting" ? (isApiKey ? "Saving..." : "Opening...") : (isApiKey ? "Add API Key" : "Connect")}
              </button>
            )}
          </div>
        </div>

        {/* API key inline input (Instantly and similar) */}
        {isApiKey && showApiKeyInput && !isConnected && (
          <div className="mt-4 flex items-center gap-2">
            <input
              type="password"
              value={apiKeyInput}
              onChange={e => setApiKeyInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleConnectApiKey()}
              placeholder="Paste your API key…"
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-amber-500"
              autoFocus
            />
            <button
              onClick={handleConnectApiKey}
              disabled={!apiKeyInput.trim() || status === "connecting"}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
            >
              {status === "connecting" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Save
            </button>
            <button
              onClick={() => { setShowApiKeyInput(false); setApiKeyInput(""); }}
              className="px-3 py-2 rounded-lg text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Expandable capabilities */}
        <button
          onClick={() => setExpanded(v => !v)}
          className="mt-4 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide" : "Show"} capabilities
        </button>

        {expanded && (
          <div className="mt-3 space-y-1.5">
            {connector.capabilities.map(cap => (
              <div key={cap} className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-400">
                <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
                {cap}
              </div>
            ))}
            {connector.docsUrl && (
              <a
                href={connector.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-1 text-xs text-violet-500 hover:text-violet-600 transition-colors"
              >
                <ExternalLink className="h-3 w-3" />
                View docs
              </a>
            )}
            {connector.envVarsRequired.length > 0 && (
              <div className="mt-2 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Required env vars</p>
                <div className="flex flex-wrap gap-1.5">
                  {connector.envVarsRequired.map(v => (
                    <code key={v} className="text-xs px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 font-mono">
                      {v}
                    </code>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── ComingSoonCard ────────────────────────────────────────────────────────────

function ComingSoonCard({ name, tagline, icon, iconBg }: { name: string; tagline: string; icon: React.ReactNode; iconBg: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/60 dark:border-slate-700/40 bg-white/60 dark:bg-slate-900/40 p-5 opacity-60 cursor-not-allowed">
      <div className="flex items-center gap-3">
        <div className={`flex-shrink-0 h-10 w-10 rounded-xl flex items-center justify-center ${iconBg}`}>
          {icon}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-slate-700 dark:text-slate-300">{name}</span>
            <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 uppercase tracking-wide">
              Soon
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">{tagline}</p>
        </div>
      </div>
    </div>
  );
}

// ─── CustomServersSection ──────────────────────────────────────────────────────

function CustomServersSection({ sessionTimeout: _sessionTimeout }: { sessionTimeout?: SessionTimeout }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "", provider: "custom", url: "", transport: "http",
    auth_type: "oauth2", capabilities_json: [] as string[], enabled: true, priority: 100,
  });

  const { data: servers = [], isLoading: loading } = useMCPServers();
  const createServer = useCreateMCPServer();
  const deleteServer = useDeleteMCPServer();
  const discoverTools = useDiscoverMCPTools();
  const pingHealth = usePingMCPHealth();

  const save = async () => {
    await createServer.mutateAsync(form);
    setShowForm(false);
    setForm({ name: "", provider: "custom", url: "", transport: "http", auth_type: "oauth2", capabilities_json: [], enabled: true, priority: 100 });
  };

  const remove = async (id: number, name: string) => {
    if (!confirm(`Delete "${name}"?`)) return;
    deleteServer.mutate(id);
  };

  const saving = createServer.isPending;

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700/60">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Custom MCP Servers</span>
          <span className="text-xs text-slate-400 ml-1">— add any MCP-compatible server</span>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-violet-600 text-white hover:bg-violet-700 transition-colors"
        >
          <Plus className="h-4 w-4" /> Add Server
        </button>
      </div>

      {showForm && (
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700/60 bg-slate-50 dark:bg-slate-800/40">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 sm:col-span-1">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Name</label>
              <input
                value={form.name}
                onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                placeholder="my_custom_server"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
            <div className="col-span-2 sm:col-span-1">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">Provider</label>
              <select
                value={form.provider}
                onChange={e => setForm(p => ({ ...p, provider: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              >
                <option value="custom">Custom</option>
                <option value="apollo">Apollo</option>
                <option value="zoho">Zoho</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">URL</label>
              <input
                value={form.url}
                onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
                placeholder="https://mcp.example.com/mcp"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-3">
            <button
              onClick={() => setShowForm(false)}
              className="px-3 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving || !form.name || !form.url}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Save
            </button>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : servers.length === 0 ? (
          <div className="py-8 text-center text-sm text-slate-400">
            No custom servers added yet. Use the button above to add one.
          </div>
        ) : (
          servers.map(s => (
            <div key={s.id} className="flex items-center gap-3 px-5 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-900 dark:text-slate-100">{s.name}</span>
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 uppercase">
                    {s.provider}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                      s.last_health_status === "healthy"
                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        : s.last_health_status === "unhealthy"
                        ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                        : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
                    }`}
                  >
                    {s.last_health_status ?? "unknown"}
                  </span>
                </div>
                <p className="text-xs text-slate-400 font-mono mt-0.5 truncate">{s.url}</p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  title="Discover tools"
                  disabled={discoverTools.isPending && discoverTools.variables === s.id}
                  onClick={() => discoverTools.mutate(s.id)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors disabled:opacity-50"
                >
                  {discoverTools.isPending && discoverTools.variables === s.id
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <RefreshCw className="h-4 w-4" />}
                </button>
                <button
                  title="Ping health"
                  disabled={pingHealth.isPending && pingHealth.variables === s.id}
                  onClick={() => pingHealth.mutate(s.id)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
                >
                  <Play className="h-4 w-4" />
                </button>
                <button
                  title="Delete"
                  onClick={() => remove(s.id, s.name)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─── MCPConnectionsTab (main export) ──────────────────────────────────────────

export default function MCPConnectionsTab({ sessionTimeout }: { sessionTimeout?: SessionTimeout }) {
  return (
    <div className="space-y-8 max-w-3xl">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">Connectors</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Connect your CRM and sales tools. Rio's AI agents get access to these integrations during calls and outreach.
        </p>
      </div>

      {/* Live connectors */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-3">
          Available
        </h3>
        <div className="space-y-3">
          {CONNECTORS.map(c => (
            <ConnectorCard key={c.id} connector={c} sessionTimeout={sessionTimeout} />
          ))}
        </div>
      </section>

      {/* Coming soon grid */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-3">
          Coming soon
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {COMING_SOON.map(c => (
            <ComingSoonCard key={c.name} {...c} />
          ))}
        </div>
      </section>

      {/* Custom MCP servers */}
      <section>
        <CustomServersSection sessionTimeout={sessionTimeout} />
      </section>
    </div>
  );
}
