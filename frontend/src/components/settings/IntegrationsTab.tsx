"use client";

import { useEffect, useState, useCallback } from "react";
import { Zap, Link2, Copy, FileCode, Check, Loader2, ArrowRight } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");
const CRM_BASE = `${API_BASE}/crm`;

export default function IntegrationsTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [events, setEvents] = useState<any[]>([]);
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Payload State
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const [samplePayload, setSamplePayload] = useState<any>(null);
  const [fetchingPayload, setFetchingPayload] = useState(false);
  const [copied, setCopied] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [eventsRes, platformsRes] = await Promise.all([
        apiFetch(`${CRM_BASE}/integrations/events`),
        apiFetch(`${CRM_BASE}/integrations/platforms`),
      ]);
      if (eventsRes.status === 401 || platformsRes.status === 401) {
        sessionTimeout();
        return;
      }
      if (eventsRes.ok) setEvents(await eventsRes.json());
      if (platformsRes.ok) setPlatforms(await platformsRes.json());
    } catch (e) {
      console.error("Failed to load integrations metadata", e);
    } finally {
      setLoading(false);
    }
  }, [sessionTimeout]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const loadSamplePayload = async (eventType: string) => {
    if (selectedEvent === eventType) {
      setSelectedEvent(null);
      setSamplePayload(null);
      return;
    }
    setSelectedEvent(eventType);
    setFetchingPayload(true);
    setSamplePayload(null);
    try {
      const res = await apiFetch(`${CRM_BASE}/integrations/sample-payload/${eventType}`);
      if (res.ok) {
        setSamplePayload(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch sample payload", e);
    } finally {
      setFetchingPayload(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-violet-500" />
        Loading integration platforms and events...
      </div>
    );
  }

  // Pre-configured platforms guides if backend response is simple list
  const defaultPlatforms = [
    {
      id: "zapier",
      name: "Zapier",
      description: "Connect Rio CRM to 5,000+ apps. Trigger workflows on call finish or new lead capture.",
      logo: "⚡",
      guide: [
        "Create a new Zap in Zapier and choose 'Webhooks by Zapier' as the Trigger.",
        "Select 'Catch Hook' as the Event and copy the unique Custom Webhook URL.",
        "Go to the Webhooks Tab in Rio settings, click 'Add Webhook' and paste the URL.",
        "Choose events like 'call.completed' or 'lead.created' to publish to Zapier.",
        "Trigger a test event from Rio and map fields in Zapier to any destination application."
      ]
    },
    {
      id: "make",
      name: "Make.com (Integromat)",
      description: "Design advanced visual workflows. Parse call sentiment, transcripts, or update external databases.",
      logo: "🧩",
      guide: [
        "In Make.com, create a new Scenario and add a 'Custom Webhook' trigger.",
        "Copy the Make webhook URL to your clipboard.",
        "Create a webhook in Rio CRM settings mapping the desired outbound events.",
        "Run the Make module once to listen for incoming structures.",
        "Test the webhook from Rio to send a schema payload, allowing Make to automatically map the JSON parameters."
      ]
    },
    {
      id: "n8n",
      name: "n8n.io",
      description: "Self-hostable node-based automation. Process quotes, orders, or dispatch custom WhatsApp notifications.",
      logo: "⚙️",
      guide: [
        "Add a Webhook Node in your n8n workflow and set the HTTP method to POST.",
        "Copy the Production or Test Webhook URL from n8n.",
        "Add the endpoint in your Rio settings panel with corresponding event subscriptions.",
        "n8n will capture lead variables, call costs, and dispositions to feed downstream databases."
      ]
    }
  ];

  const platformsList = platforms.length > 0 ? platforms : defaultPlatforms;

  return (
    <div className="space-y-8">
      {/* Platform Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {platformsList.map(p => (
          <div key={p.id || p.name} className="rounded-2xl glass p-5 border border-white/40 dark:border-white/10 flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-lg">
                  {p.logo || "🔌"}
                </div>
                <h4 className="font-bold text-slate-800 dark:text-white text-base">{p.name}</h4>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">{p.description}</p>
            </div>
            
            <div className="space-y-2 pt-2 border-t border-slate-150 dark:border-slate-800/60">
              <span className="text-[10px] font-bold text-slate-400 block uppercase tracking-wider">Quick Setup Guide</span>
              <ol className="list-decimal pl-4 text-[11px] text-slate-650 dark:text-slate-350 space-y-1">
                {(p.guide || []).map((step: string, idx: number) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
            </div>
          </div>
        ))}
      </div>

      {/* Events Payload Sandbox */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-yellow-500 to-amber-600">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Outbound Event Payloads</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">Preview raw JSON schemas sent by Rio CRM webhooks for each event type</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="space-y-2 md:col-span-1 border-r border-slate-200 dark:border-slate-800 pr-6">
            <span className="text-[10px] font-bold text-slate-400 block uppercase tracking-wider mb-2">Select Event Type</span>
            <div className="flex flex-col gap-1.5 max-h-80 overflow-y-auto pr-2">
              {events.map((e: any) => {
                const eventKey = typeof e === "string" ? e : e.key;
                const eventLabel = typeof e === "string" ? e : e.label;
                return (
                  <button
                    key={eventKey}
                    onClick={() => loadSamplePayload(eventKey)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs font-mono font-semibold transition-all flex items-center justify-between group ${
                      selectedEvent === eventKey
                        ? "bg-violet-600 text-white"
                        : "bg-slate-50/50 hover:bg-slate-100 dark:bg-slate-900/30 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300"
                    }`}
                  >
                    <span>{eventLabel}</span>
                    <ArrowRight className={`h-3 w-3 transition-transform ${selectedEvent === eventKey ? "translate-x-0.5" : "opacity-0 group-hover:opacity-100"}`} />
                  </button>
                );
              })}
            </div>
          </div>

          <div className="md:col-span-2 space-y-3 flex flex-col justify-start">
            <span className="text-[10px] font-bold text-slate-400 block uppercase tracking-wider">JSON Payload Preview</span>
            
            {!selectedEvent ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-slate-50/20 dark:bg-slate-900/10 border border-dashed border-slate-250 dark:border-slate-800 rounded-xl min-h-[220px]">
                <FileCode className="h-8 w-8 text-slate-350 dark:text-slate-600 mb-2" />
                <p className="text-xs text-slate-400">Click on any event type on the left to load its sample JSON structure.</p>
              </div>
            ) : fetchingPayload ? (
              <div className="flex-1 flex items-center justify-center min-h-[220px] text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin mr-2 text-violet-500" />
                Loading schema...
              </div>
            ) : samplePayload ? (
              <div className="relative flex-1 flex flex-col">
                <button
                  onClick={() => copyToClipboard(JSON.stringify(samplePayload, null, 2))}
                  className="absolute right-3 top-3 px-2 py-1 rounded bg-slate-850 hover:bg-slate-800 text-slate-300 text-[10px] flex items-center gap-1 transition-colors border border-slate-700"
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                  {copied ? "Copied!" : "Copy JSON"}
                </button>
                <pre className="p-4 bg-slate-900 text-slate-100 rounded-xl text-[11px] font-mono overflow-auto max-h-96 min-h-[220px] border border-slate-850 whitespace-pre-wrap">
                  {JSON.stringify(samplePayload, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-slate-400">Could not retrieve payload schema for this event.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
