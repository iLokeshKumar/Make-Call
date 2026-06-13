"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BrainCircuit, CheckCircle2, ClipboardList, PhoneCall, Users, ShoppingCart, Receipt, Ticket, Wrench } from "lucide-react";

import AIRecommendation from "@/components/dashboard/ai_recommendation";
import MetricCard from "@/components/dashboard/metric_card";
import RecentActivity from "@/components/dashboard/recent_activity";
import TodaysCallTask from "@/components/dashboard/todays_call_task";
import AnalyticsSummary from "@/components/dashboard/analytics_summary";
import IsmLiveWidget from "@/components/dashboard/ism_live_widget";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
import { reportUiLatency } from "@/utils/uiLatency";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type Lead = {
  id: number;
  name: string;
  normalized_phone?: string | null;
  email?: string | null;
  status: string;
  qualification_status?: string | null;
  next_action?: string | null;
  next_action_due_at?: string | null;
  source?: string | null;
  notes?: string | null;
  created_at?: string;
};

type CallTask = {
  id: number;
  lead_id: number;
  status: string;
  scheduled_at?: string | null;
  completed_at?: string | null;
  notes?: string | null;
};

function formatShortDate(value?: string | null) {
  if (!value) return "No due date";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "No due date";
  return parsed.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function humanize(value?: string | null) {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function Home() {
  const { user, sessionTimeout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [tasks, setTasks] = useState<CallTask[]>([]);

  // Beacon for SLO #2 (login → dashboard p95).  Fires once per page-load.
  useEffect(() => {
    if (!user) return;
    reportUiLatency("/", "fmp");
  }, [user]);

  useEffect(() => {
    async function fetchDashboardData() {
      if (!user) {
        setLoading(false);
        return;
      }

      try {
        const [leadsRes, tasksRes] = await Promise.all([
          apiFetch(`${API_BASE}/crm/leads?page=1&limit=100`, {
          }),
          apiFetch(`${API_BASE}/call-tasks`, {
          }),
        ]);

        if (leadsRes.status === 401 || tasksRes.status === 401) {
          sessionTimeout();
          return;
        }

        if (leadsRes.ok) {
          const leadPayload = await leadsRes.json();
          setLeads(leadPayload.items || []);
        }

        if (tasksRes.ok) {
          const taskPayload = await tasksRes.json();
          setTasks(Array.isArray(taskPayload) ? taskPayload : []);
        }
      } catch (error) {
        console.error("Failed to load dashboard data", error);
      } finally {
        setLoading(false);
      }
    }

    fetchDashboardData();
  }, [user, sessionTimeout]);

  const leadMap = useMemo(() => new Map(leads.map((lead) => [lead.id, lead])), [leads]);

  const metrics = useMemo(
    () => [
      {
        title: "Total Leads",
        value: leads.length,
        helper: "Company pipeline right now",
        icon: Users,
        tone: "blue" as const },
      {
        title: "Open Call Tasks",
        value: tasks.filter((task) => ["pending", "queued", "dialing"].includes(task.status)).length,
        helper: "Need action from the team",
        icon: PhoneCall,
        tone: "emerald" as const },
      {
        title: "Qualified Leads",
        value: leads.filter((lead) => ["qualified", "proposal", "follow_up"].includes((lead.qualification_status || "").toLowerCase())).length,
        helper: "Moved beyond raw prospecting",
        icon: CheckCircle2,
        tone: "violet" as const },
      {
        title: "Next Actions",
        value: leads.filter((lead) => lead.next_action && lead.next_action !== "none").length,
        helper: "AI or rep follow-up suggestions",
        icon: ClipboardList,
        tone: "orange" as const },
    ],
    [leads, tasks]
  );

  const todayTasks = useMemo(
    () =>
      tasks
        .filter((task) => ["pending", "queued", "dialing"].includes(task.status))
        .sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""))
        .slice(0, 5)
        .map((task) => ({
          id: task.id,
          leadId: task.lead_id,
          leadName: leadMap.get(task.lead_id)?.name || `Lead #${task.lead_id}`,
          status: task.status,
          scheduledAt: task.scheduled_at,
          note: task.notes })),
    [leadMap, tasks]
  );

  const recentActivity = useMemo(() => {
    const leadItems = leads.slice(0, 4).map((lead) => ({
      id: `lead-${lead.id}`,
      title: `${lead.name} added to pipeline`,
      subtitle: lead.notes || `${humanize(lead.status)} · ${humanize(lead.source)}`,
      timestamp: lead.created_at,
      status: lead.status === "new" ? ("new" as const) : ("success" as const) }));

    const taskItems = tasks.slice(0, 4).map((task) => ({
      id: `task-${task.id}`,
      title: `Call task #${task.id} is ${humanize(task.status)}`,
      subtitle: leadMap.get(task.lead_id)?.name || `Lead #${task.lead_id}`,
      timestamp: task.completed_at || task.scheduled_at,
      status:
        task.status === "failed"
          ? ("warning" as const)
          : task.status === "completed"
            ? ("success" as const)
            : ("pending" as const) }));

    return [...leadItems, ...taskItems]
      .sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""))
      .slice(0, 6);
  }, [leadMap, leads, tasks]);

  const recommendations = useMemo(() => {
    const recommended = leads
      .filter((lead) => lead.next_action && lead.next_action !== "none")
      .slice(0, 4)
      .map((lead) => ({
        id: lead.id,
        title: `${humanize(lead.next_action)} for ${lead.name}`,
        description:
          lead.notes || `Qualification: ${humanize(lead.qualification_status)} · Due ${formatShortDate(lead.next_action_due_at)}`,
        href: `/leads/${lead.id}`,
        ctaLabel: "Open Lead 360" }));

    if (recommended.length > 0) return recommended;

    return [
      {
        id: 1,
        title: "Start with today’s call queue",
        description: "Use the dashboard to work pending outreach in order.",
        href: "/leads",
        ctaLabel: "Review leads" },
      {
        id: 2,
        title: "Open Lead 360 after each call",
        description: "Reps should confirm AI insights and schedule the next action immediately.",
        href: "/leads",
        ctaLabel: "See pipeline" },
    ];
  }, [leads]);

  return (
    <div className="space-y-8 pb-8">
      <div className="relative overflow-hidden rounded-3xl glass p-8 border border-white/40 dark:border-white/10">
        <div className="absolute inset-0 bg-gradient-to-r from-violet-600/10 via-blue-600/10 to-purple-600/10 dark:from-violet-900/20 dark:via-blue-900/20 dark:to-purple-900/20" />
        <div className="relative z-10 flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">Sales command center</p>
            <h1 className="mt-2 text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
              Welcome back, <span className="gradient-text">{user?.first_name || user?.username || "Team"}</span>
            </h1>
            <p className="mt-3 text-slate-600 dark:text-slate-300">
              This dashboard now maps directly to your backend: leads, call tasks, and AI-suggested next actions are all surfaced in one workflow-first view.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              href="/leads"
              className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-violet-600 to-blue-600 px-5 py-3 font-semibold text-white shadow-lg shadow-violet-500/30 transition hover:scale-[1.02]"
            >
              Open pipeline <ArrowRight className="h-4 w-4" />
            </Link>
            <div className="rounded-2xl border border-white/40 bg-white/70 px-4 py-3 text-sm text-slate-700 dark:border-white/10 dark:bg-slate-900/40 dark:text-slate-200">
              <span className="font-semibold">Live focus:</span> rep dashboard + Lead 360
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard
            key={metric.title}
            title={metric.title}
            value={loading ? "..." : metric.value.toString()}
            helper={metric.helper}
            icon={metric.icon}
            tone={metric.tone}
          />
        ))}
      </div>

      <AnalyticsSummary />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <TodaysCallTask items={todayTasks} loading={loading} />
          <RecentActivity items={recentActivity} loading={loading} />
        </div>

        <div className="space-y-6">
          <IsmLiveWidget />
          <AIRecommendation items={recommendations} loading={loading} />

          <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10">
            <div className="flex items-start gap-3">
              <div className="rounded-xl bg-violet-100 p-3 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                <BrainCircuit className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Why this dashboard matters</h2>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                  The backend already handles automation. This UI makes it actionable by showing what happened, what matters, and what the rep should do next.
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Operations</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "Orders", href: "/orders", icon: ShoppingCart, color: "text-blue-600 dark:text-blue-400" },
                { label: "Invoices", href: "/invoices", icon: Receipt, color: "text-emerald-600 dark:text-emerald-400" },
                { label: "Tickets", href: "/tickets", icon: Ticket, color: "text-amber-600 dark:text-amber-400" },
                { label: "Installations", href: "/installations", icon: Wrench, color: "text-violet-600 dark:text-violet-400" },
              ].map(({ label, href, icon: Icon, color }) => (
                <Link
                  key={href}
                  href={href}
                  className="flex items-center gap-2 rounded-xl border border-white/30 bg-white/40 px-3 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-white/70 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10"
                >
                  <Icon className={`h-4 w-4 ${color}`} />
                  {label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
