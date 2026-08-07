"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  CheckCircle2, Loader2, ExternalLink, Unplug, Plug,
  Plus, RefreshCw, Trash2, Play, Network, Database,
  Search, Calendar, Mail, BookOpen, AlertCircle,
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
  category: "crm" | "enrichment" | "scheduling" | "communication" | "accounting";
  icon: React.ReactNode;
  iconBg: string;
  authType?: "oauth" | "apikey";
  authUrl?: string;
  connectUrl?: string;
  apiKeyJsonField?: string;
  apiKeyPlaceholder?: string;
  statusUrl: string;
  disconnectUrl: string;
  capabilities: string[];
  docsUrl?: string;
  envVarsRequired: string[];
};

type MCPServer = MCPServerRecord;

// ─── category config ──────────────────────────────────────────────────────────

const CATEGORIES: Record<ConnectorDef["category"], {
  label: string;
  icon: React.ReactNode;
  accent: string;
  border: string;
}> = {
  crm: {
    label: "CRM",
    icon: <Database className="h-4 w-4" />,
    accent: "text-blue-600 dark:text-blue-400",
    border: "border-blue-200 dark:border-blue-800",
  },
  enrichment: {
    label: "Enrichment & Prospecting",
    icon: <Search className="h-4 w-4" />,
    accent: "text-violet-600 dark:text-violet-400",
    border: "border-violet-200 dark:border-violet-800",
  },
  scheduling: {
    label: "Scheduling",
    icon: <Calendar className="h-4 w-4" />,
    accent: "text-emerald-600 dark:text-emerald-400",
    border: "border-emerald-200 dark:border-emerald-800",
  },
  communication: {
    label: "Communication",
    icon: <Mail className="h-4 w-4" />,
    accent: "text-sky-600 dark:text-sky-400",
    border: "border-sky-200 dark:border-sky-800",
  },
  accounting: {
    label: "Accounting",
    icon: <BookOpen className="h-4 w-4" />,
    accent: "text-indigo-600 dark:text-indigo-400",
    border: "border-indigo-200 dark:border-indigo-800",
  },
};

// ─── connector definitions ────────────────────────────────────────────────────

const CONNECTORS: ConnectorDef[] = [
  {
    id: "zoho",
    name: "Zoho CRM",
    tagline: "Two-way sync of deals, contacts, and pipeline stages",
    category: "crm",
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
    ],
    envVarsRequired: ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET"],
    docsUrl: "https://api-console.zoho.com/",
  },
  {
    id: "hubspot",
    name: "HubSpot",
    tagline: "CRM sync — contacts, deals, companies, and pipeline stages",
    category: "crm",
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
    ],
    envVarsRequired: ["HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"],
    docsUrl: "https://developers.hubspot.com/",
  },
  {
    id: "salesforce",
    name: "Salesforce",
    tagline: "Enterprise CRM — contacts, opportunities, and pipeline sync",
    category: "crm",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#00A1E0" />
        <path
          d="M20 9c-2.5 0-4.7 1.3-6 3.3a5.5 5.5 0 0 0-7 5.3c0 3 2.5 5.5 5.5 5.5h14a5 5 0 0 0 0-10 5 5 0 0 0-.6 0A6 6 0 0 0 20 9z"
          fill="white" fillOpacity="0.95"
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
    ],
    envVarsRequired: ["SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"],
    docsUrl: "https://developer.salesforce.com/",
  },
  {
    id: "apollo",
    name: "Apollo.io",
    tagline: "Lead enrichment, prospecting, and outreach sequencing",
    category: "enrichment",
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
    ],
    envVarsRequired: ["APOLLO_CLIENT_ID", "APOLLO_CLIENT_SECRET"],
    docsUrl: "https://developer.apollo.io/",
  },
  {
    id: "rocketreach",
    name: "RocketReach",
    tagline: "Verified emails, phones & LinkedIn from 700M+ profiles",
    category: "enrichment",
    authType: "apikey",
    connectUrl: `${API_BASE}/crm/rocketreach/connect`,
    statusUrl: `${API_BASE}/crm/rocketreach/status`,
    disconnectUrl: `${API_BASE}/crm/rocketreach/disconnect`,
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#FF6B2B" />
        <path d="M12 28 L20 10 L24 18 L28 14" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="28" cy="14" r="3" fill="white" />
      </svg>
    ),
    iconBg: "bg-orange-50 dark:bg-orange-900/20",
    capabilities: [
      "Enrich leads with verified work emails & direct dials",
      "Search 700M+ professional profiles globally",
      "Find decision-makers by title + company",
    ],
    envVarsRequired: [],
    docsUrl: "https://rocketreach.co/api",
  },
  {
    id: "rocketreach_mcp",
    name: "RocketReach MCP",
    tagline: "Full MCP access — bulk lookup, company search & AI-native enrichment",
    category: "enrichment",
    authUrl: `${API_BASE}/crm/rocketreach-mcp/auth-url`,
    statusUrl: `${API_BASE}/crm/rocketreach-mcp/status`,
    disconnectUrl: `${API_BASE}/crm/rocketreach-mcp/disconnect`,
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#FF6B2B" />
        <path d="M12 28 L20 10 L24 18 L28 14" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="28" cy="14" r="3" fill="white" />
        <circle cx="12" cy="28" r="2.5" fill="white" fillOpacity="0.6" />
      </svg>
    ),
    iconBg: "bg-orange-50 dark:bg-orange-900/20",
    capabilities: [
      "Bulk person & company lookup via MCP tools",
      "AI agents call enrichment natively during calls",
      "Fallback enrichment when Apollo is unavailable",
    ],
    envVarsRequired: [],
    docsUrl: "https://rocketreach.co/api",
  },
  {
    id: "linkedin",
    name: "LinkedIn Sales Navigator",
    tagline: "Prospect smarter with AI-powered lead recommendations",
    category: "enrichment",
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
    ],
    envVarsRequired: ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"],
    docsUrl: "https://developer.linkedin.com/",
  },
  {
    id: "calcom",
    name: "Cal.com",
    tagline: "AI scheduling — book, reschedule & check availability during calls",
    category: "scheduling",
    authUrl: `${API_BASE}/crm/calcom/auth-url`,
    statusUrl: `${API_BASE}/crm/calcom/status`,
    disconnectUrl: `${API_BASE}/crm/calcom/disconnect`,
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#111827" />
        <rect x="10" y="11" width="20" height="18" rx="2" stroke="white" strokeWidth="1.8" fill="none" />
        <line x1="10" y1="16" x2="30" y2="16" stroke="white" strokeWidth="1.8" />
        <line x1="15" y1="8" x2="15" y2="14" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="25" y1="8" x2="25" y2="14" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="20" cy="23" r="2.5" fill="white" fillOpacity="0.9" />
      </svg>
    ),
    iconBg: "bg-slate-900 dark:bg-slate-800",
    capabilities: [
      "Book meetings with leads during AI calls",
      "Check rep availability before scheduling",
      "Reschedule or cancel via voice commands",
    ],
    envVarsRequired: [],
    docsUrl: "https://cal.com/docs/mcp-server",
  },
  {
    id: "calendly",
    name: "Calendly",
    tagline: "AI scheduling — book, check availability & manage events via Calendly",
    category: "scheduling",
    authUrl: `${API_BASE}/crm/calendly/auth-url`,
    statusUrl: `${API_BASE}/crm/calendly/status`,
    disconnectUrl: `${API_BASE}/crm/calendly/disconnect`,
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#006BFF" />
        <rect x="10" y="11" width="20" height="18" rx="2" stroke="white" strokeWidth="1.8" fill="none" />
        <line x1="10" y1="16" x2="30" y2="16" stroke="white" strokeWidth="1.8" />
        <line x1="15" y1="8" x2="15" y2="14" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="25" y1="8" x2="25" y2="14" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
        <rect x="14" y="20" width="5" height="5" rx="1" fill="white" fillOpacity="0.9" />
      </svg>
    ),
    iconBg: "bg-blue-600 dark:bg-blue-700",
    capabilities: [
      "Book meetings with leads during AI calls",
      "Check availability for any event type",
      "Generate single-use scheduling links",
    ],
    envVarsRequired: [],
    docsUrl: "https://developer.calendly.com/calendly-mcp-server",
  },
  {
    id: "google",
    name: "Google Workspace",
    tagline: "Calendar, Meet, Gmail, Drive & Sheets — one connection",
    category: "communication",
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
    iconBg: "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700",
    authUrl: `${API_BASE}/crm/calendar/auth-url`,
    statusUrl: `${API_BASE}/crm/calendar/status`,
    disconnectUrl: `${API_BASE}/crm/calendar/disconnect`,
    capabilities: [
      "Book & manage Google Calendar meetings",
      "Send & read emails via Gmail",
      "Read/write Google Drive files & Sheets",
    ],
    envVarsRequired: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
    docsUrl: "https://console.cloud.google.com/",
  },
  {
    id: "microsoft",
    name: "Microsoft 365",
    tagline: "Outlook email, OneDrive files & Teams calendar — one connection",
    category: "communication",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="white" />
        <rect x="8" y="8" width="11" height="11" fill="#F25022" />
        <rect x="21" y="8" width="11" height="11" fill="#7FBA00" />
        <rect x="8" y="21" width="11" height="11" fill="#00A4EF" />
        <rect x="21" y="21" width="11" height="11" fill="#FFB900" />
      </svg>
    ),
    iconBg: "bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700",
    authUrl: `${API_BASE}/crm/microsoft/auth-url`,
    statusUrl: `${API_BASE}/crm/microsoft/status`,
    disconnectUrl: `${API_BASE}/crm/microsoft/disconnect`,
    capabilities: [
      "Read & send emails via Outlook",
      "Read & write Outlook Calendar events",
      "Access and upload OneDrive files",
    ],
    envVarsRequired: ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"],
    docsUrl: "https://portal.azure.com/",
  },
  {
    id: "instantly",
    name: "Instantly",
    tagline: "Cold email sequencing and deliverability at scale",
    category: "communication",
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
    ],
    envVarsRequired: [],
    docsUrl: "https://app.instantly.ai/app/settings/integrations",
  },
  {
    id: "tally",
    name: "Tally Prime",
    tagline: "Post vouchers from Zoho Books directly to Tally via local gateway",
    category: "accounting",
    authType: "apikey",
    connectUrl: `${API_BASE}/crm/tally/connect`,
    statusUrl: `${API_BASE}/crm/tally/status`,
    disconnectUrl: `${API_BASE}/crm/tally/disconnect`,
    apiKeyJsonField: "gateway_url",
    apiKeyPlaceholder: "http://localhost:9000",
    icon: (
      <svg viewBox="0 0 40 40" className="h-7 w-7" fill="none">
        <rect width="40" height="40" rx="8" fill="#1B4FBB" />
        <text x="20" y="27" textAnchor="middle" fill="white" fontSize="14" fontWeight="bold" fontFamily="Arial">T</text>
      </svg>
    ),
    iconBg: "bg-blue-50 dark:bg-blue-900/20",
    capabilities: [
      "Post sales invoices, receipts & payments to Tally",
      "Works with Tally Prime 2.x via Gateway of Tally",
      "Voucher-level audit trail with retry on failure",
    ],
    envVarsRequired: [],
    docsUrl: "https://help.tallysolutions.com/",
  },
];

// ─── ConnectorCard ─────────────────────────────────────────────────────────────

function ConnectorCard({ connector, sessionTimeout }: { connector: ConnectorDef; sessionTimeout?: SessionTimeout }) {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [toast, setToast] = useState<string | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [showApiKeyInput, setShowApiKeyInput] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();

  const isApiKey = connector.authType === "apikey";
  const cat = CATEGORIES[connector.category];

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

  useEffect(() => { checkStatus(); }, [checkStatus]);

  useEffect(() => {
    const param = searchParams.get(connector.id);
    if (param === "connected") {
      setStatus("connected");
      setToast(`${connector.name} connected`);
      setTimeout(() => setToast(null), 4000);
      const url = new URL(window.location.href);
      url.searchParams.delete(connector.id);
      router.replace(url.pathname + (url.search || ""), { scroll: false });
    }
  }, [searchParams, connector.id, connector.name, router]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
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
            setToast(`${connector.name} connected`);
            setTimeout(() => setToast(null), 4000);
            stopPolling();
            return;
          }
        }
      } catch { /* ignore */ }
      if (attempts >= 30) { stopPolling(); setStatus("disconnected"); }
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
        body: JSON.stringify({ [connector.apiKeyJsonField ?? "api_key"]: apiKeyInput.trim() }),
      });
      if (res.status === 401) { sessionTimeout?.(); setStatus("disconnected"); return; }
      if (!res.ok) {
        let detail = "Invalid API key";
        try { const body = await res.json(); detail = body.detail ?? detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      setStatus("connected");
      setToast(`${connector.name} connected`);
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
    if (isApiKey) { setShowApiKeyInput(true); return; }
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
      const popup = window.open(auth_url, "oauth_popup", "width=600,height=700,left=400,top=100");
      if (!popup || popup.closed || typeof popup.closed === "undefined") window.open(auth_url, "_blank");
      startPolling();
    } catch (err: unknown) {
      setStatus("error");
      setToast(err instanceof Error ? err.message : "Connection failed");
      setTimeout(() => setToast(null), 4000);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm(`Disconnect ${connector.name}? Rio agents will lose access.`)) return;
    try {
      const res = await apiFetch(connector.disconnectUrl, { method: "DELETE" });
      if (res.status === 401) { sessionTimeout?.(); return; }
      setStatus("disconnected");
      setToast(`${connector.name} disconnected`);
      setTimeout(() => setToast(null), 3000);
    } catch {
      setToast("Disconnect failed");
      setTimeout(() => setToast(null), 3000);
    }
  };

  const isConnected = status === "connected";
  const isLoading = status === "checking" || status === "connecting";

  return (
    <div className={`relative rounded-2xl border bg-white dark:bg-slate-900 flex flex-col transition-all duration-200 ${
      isConnected
        ? `${cat.border} shadow-sm`
        : "border-slate-200 dark:border-slate-700/60"
    }`}>
      {/* Connected top bar */}
      {isConnected && (
        <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-2xl bg-gradient-to-r from-green-400 to-emerald-500" />
      )}

      {/* Toast */}
      {toast && (
        <div className="absolute top-3 right-3 z-10 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-medium shadow-lg">
          <CheckCircle2 className="h-3.5 w-3.5 text-green-400 dark:text-green-600 flex-shrink-0" />
          {toast}
        </div>
      )}

      <div className="p-5 flex flex-col gap-4 flex-1">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className={`flex-shrink-0 h-11 w-11 rounded-xl flex items-center justify-center ${connector.iconBg}`}>
            {connector.icon}
          </div>
          <div className="flex-1 min-w-0 pt-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-bold text-slate-900 dark:text-slate-100 leading-none">{connector.name}</span>
              {status === "checking" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-400">
                  <Loader2 className="h-2.5 w-2.5 animate-spin" /> Checking
                </span>
              ) : isConnected ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" /> Connected
                </span>
              ) : status === "connecting" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400">
                  <Loader2 className="h-2.5 w-2.5 animate-spin" /> Connecting
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 leading-snug">{connector.tagline}</p>
          </div>
        </div>

        {/* Capabilities */}
        <ul className="space-y-1.5 flex-1">
          {connector.capabilities.map(cap => (
            <li key={cap} className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
              <CheckCircle2 className="h-3.5 w-3.5 text-green-500 flex-shrink-0 mt-0.5" />
              {cap}
            </li>
          ))}
        </ul>

        {/* Env vars warning */}
        {connector.envVarsRequired.length > 0 && !isConnected && (
          <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40">
            <AlertCircle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
            <div className="flex flex-wrap gap-1">
              {connector.envVarsRequired.map(v => (
                <code key={v} className="text-[10px] px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-mono">{v}</code>
              ))}
            </div>
          </div>
        )}

        {/* API key input */}
        {isApiKey && showApiKeyInput && !isConnected && (
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={apiKeyInput}
              onChange={e => setApiKeyInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleConnectApiKey()}
              placeholder={connector.apiKeyPlaceholder ?? "Paste your API key…"}
              className="flex-1 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
              autoFocus
            />
            <button
              onClick={handleConnectApiKey}
              disabled={!apiKeyInput.trim() || status === "connecting"}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {status === "connecting" ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
            </button>
            <button
              onClick={() => { setShowApiKeyInput(false); setApiKeyInput(""); }}
              className="px-2 py-1.5 rounded-lg text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              ✕
            </button>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-slate-100 dark:border-slate-800">
          {connector.docsUrl ? (
            <a
              href={connector.docsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-violet-500 transition-colors"
            >
              <ExternalLink className="h-3 w-3" /> Docs
            </a>
          ) : <span />}

          {isConnected ? (
            <button
              onClick={handleDisconnect}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:border-red-300 hover:text-red-600 dark:hover:text-red-400 dark:hover:border-red-800 transition-colors"
            >
              <Unplug className="h-3 w-3" /> Disconnect
            </button>
          ) : (
            <button
              onClick={handleConnect}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-900 dark:bg-white text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-100 disabled:opacity-50 transition-colors"
            >
              {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plug className="h-3 w-3" />}
              {status === "connecting" ? (isApiKey ? "Saving…" : "Opening…") : (isApiKey && !showApiKeyInput ? "Add Key" : "Connect")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Custom server status helpers ────────────────────────────────────────────

function serverStatusMeta(s: MCPServer) {
  const needsAuth = s.auth_type === "oauth2" || s.auth_type === "bearer" || s.auth_type === "api_key";
  if (s.last_health_status === "healthy") {
    return {
      dot: "bg-green-400",
      label: "Connected",
      sub: "Responding to health checks",
      labelCls: "text-green-600 dark:text-green-400",
    };
  }
  if (s.last_health_status === "unhealthy") {
    if (needsAuth) {
      return {
        dot: "bg-amber-400",
        label: "Not connected",
        sub: "Authentication required — no token configured",
        labelCls: "text-amber-600 dark:text-amber-400",
      };
    }
    return {
      dot: "bg-red-400",
      label: "Unreachable",
      sub: "Server not responding — check the URL",
      labelCls: "text-red-600 dark:text-red-400",
    };
  }
  return {
    dot: "bg-slate-300 dark:bg-slate-600",
    label: "Not checked",
    sub: "Click ▶ to ping",
    labelCls: "text-slate-400",
  };
}

function authTypeBadge(auth_type: string) {
  if (auth_type === "oauth2" || auth_type === "bearer")
    return { label: "OAuth 2.0", cls: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300" };
  if (auth_type === "api_key" || auth_type === "apikey")
    return { label: "API Key", cls: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300" };
  return { label: "No Auth", cls: "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400" };
}

// ─── CustomServersSection ──────────────────────────────────────────────────────

function CustomServersSection({ sessionTimeout: _sessionTimeout }: { sessionTimeout?: SessionTimeout }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "", provider: "custom", url: "", transport: "http",
    auth_type: "none", capabilities_json: [] as string[], enabled: true, priority: 100,
  });

  const { data: servers = [], isLoading: loading } = useMCPServers();
  const createServer = useCreateMCPServer();
  const deleteServer = useDeleteMCPServer();
  const discoverTools = useDiscoverMCPTools();
  const pingHealth = usePingMCPHealth();

  const save = async () => {
    await createServer.mutateAsync(form);
    setShowForm(false);
    setForm({ name: "", provider: "custom", url: "", transport: "http", auth_type: "none", capabilities_json: [], enabled: true, priority: 100 });
  };

  const remove = async (id: number, name: string) => {
    if (!confirm(`Delete "${name}"?`)) return;
    deleteServer.mutate(id);
  };

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700/60">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-slate-400" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Custom MCP Servers</span>
          <span className="text-xs text-slate-400">— any MCP-compatible endpoint</span>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 text-white hover:bg-violet-700 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> Add Server
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700/60 bg-slate-50 dark:bg-slate-800/40 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Name</label>
              <input
                value={form.name}
                onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                placeholder="my_server"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Auth Type</label>
              <select
                value={form.auth_type}
                onChange={e => setForm(p => ({ ...p, auth_type: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              >
                <option value="none">None</option>
                <option value="bearer">Bearer Token</option>
                <option value="api_key">API Key</option>
                <option value="oauth2">OAuth 2.0</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">MCP URL</label>
              <input
                value={form.url}
                onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
                placeholder="https://mcp.example.com/mcp"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">Cancel</button>
            <button
              onClick={save}
              disabled={createServer.isPending || !form.name || !form.url}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {createServer.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null} Save
            </button>
          </div>
        </div>
      )}

      {/* Server list */}
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : servers.length === 0 ? (
          <div className="py-10 text-center">
            <Network className="h-8 w-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
            <p className="text-sm text-slate-400">No custom servers added yet.</p>
            <p className="text-xs text-slate-300 dark:text-slate-600 mt-1">Paste any MCP-compatible endpoint URL above.</p>
          </div>
        ) : servers.map(s => {
          const status = serverStatusMeta(s);
          const auth = authTypeBadge(s.auth_type);
          return (
            <div key={s.id} className="flex items-start gap-3 px-5 py-4">
              {/* Status dot */}
              <div className={`mt-[5px] h-2 w-2 rounded-full flex-shrink-0 ${status.dot}`} />

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{s.name}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide ${auth.cls}`}>
                    {auth.label}
                  </span>
                  <span className={`text-xs font-medium ${status.labelCls}`}>{status.label}</span>
                </div>
                <p className="text-xs text-slate-400 font-mono mt-0.5 truncate">{s.url}</p>
                <p className="text-xs text-slate-400 mt-0.5">{status.sub}</p>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-0.5 flex-shrink-0">
                <button
                  title="Discover tools"
                  disabled={discoverTools.isPending && discoverTools.variables === s.id}
                  onClick={() => discoverTools.mutate(s.id)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors disabled:opacity-50"
                >
                  {discoverTools.isPending && discoverTools.variables === s.id
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <RefreshCw className="h-3.5 w-3.5" />}
                </button>
                <button
                  title="Ping health"
                  disabled={pingHealth.isPending && pingHealth.variables === s.id}
                  onClick={() => pingHealth.mutate(s.id)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors disabled:opacity-50"
                >
                  {pingHealth.isPending && pingHealth.variables === s.id
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <Play className="h-3.5 w-3.5" />}
                </button>
                <button
                  title="Remove"
                  onClick={() => remove(s.id, s.name)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── MCPConnectionsTab ────────────────────────────────────────────────────────

const CATEGORY_ORDER: ConnectorDef["category"][] = ["crm", "enrichment", "scheduling", "communication", "accounting"];

export default function MCPConnectionsTab({ sessionTimeout }: { sessionTimeout?: SessionTimeout }) {
  const grouped = CATEGORY_ORDER.map(cat => ({
    cat,
    connectors: CONNECTORS.filter(c => c.category === cat),
  })).filter(g => g.connectors.length > 0);

  return (
    <div className="space-y-10 max-w-4xl">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">Connectors</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Connect your sales stack. Rio agents get live access to these tools during calls and outreach.
        </p>
      </div>

      {/* Grouped sections */}
      {grouped.map(({ cat, connectors }) => {
        const meta = CATEGORIES[cat];
        return (
          <section key={cat}>
            <div className={`flex items-center gap-2 mb-4 ${meta.accent}`}>
              {meta.icon}
              <h3 className="text-xs font-bold uppercase tracking-wider">{meta.label}</h3>
              <span className="text-xs font-normal text-slate-400 normal-case tracking-normal">
                — {connectors.length} integration{connectors.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {connectors.map(c => (
                <ConnectorCard key={c.id} connector={c} sessionTimeout={sessionTimeout} />
              ))}
            </div>
          </section>
        );
      })}

      {/* Custom MCP servers */}
      <section>
        <CustomServersSection sessionTimeout={sessionTimeout} />
      </section>
    </div>
  );
}
