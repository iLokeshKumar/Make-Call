"use client";

import { useEffect, useState } from "react";
import { Phone, Users, CheckCircle, AlertCircle, TrendingUp, Activity } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import clsx from "clsx";

export default function Home() {
  const router = useRouter();
  const [statsData, setStatsData] = useState({
    total_leads: 0,
    calls_today: 0,
    converted: 0,
    follow_up: 0
  });

  const [activities, setActivities] = useState<any[]>([]);
  const { user, token, sessionTimeout } = useAuth();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      if (!token || token.split('.').length !== 3) {
        setLoading(false);
        return;
      }
      try {
        // Fetch Stats
        const statsRes = await fetch("http://localhost:6060/crm/dashboard/stats", {
          headers: { "Authorization": `Bearer ${token}` }
        });

        if (statsRes.status === 401) {
          sessionTimeout();
          return;
        }

        if (statsRes.ok) {
          const data = await statsRes.json();
          setStatsData(data);
        }

        // Fetch Recent Leads for Activity
        const leadsRes = await fetch("http://localhost:6060/crm/leads", {
          headers: { "Authorization": `Bearer ${token}` }
        });

        if (leadsRes.status === 401) {
          sessionTimeout();
          return;
        }
        if (leadsRes.ok) {
          const data = await leadsRes.json();
          const leads = data.items || [];
          // Map latest 5 leads to activity format
          const formattedActivities = leads.slice(0, 5).map((lead: any) => ({
            title: `Lead: ${lead.name} `,
            subtitle: lead.notes || `Contact: ${lead.phone} `,
            time: new Date(lead.created_at).toLocaleDateString(),
            status: lead.status.toLowerCase() === 'converted' ? 'success' : lead.status.toLowerCase() === 'new' ? 'new' : 'pending'
          }));
          setActivities(formattedActivities);
        }
      } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [token]);

  const stats = [
    {
      name: "Total Leads",
      value: statsData.total_leads.toString(),
      change: "+0%", // Dynamic change requires historic data, keeping static for now
      icon: Users,
      gradient: "from-blue-500 to-cyan-500",
      glow: "shadow-blue-500/50"
    },
    {
      name: "Calls Today",
      value: statsData.calls_today.toString(),
      change: "+0%",
      icon: Phone,
      gradient: "from-green-500 to-emerald-500",
      glow: "shadow-green-500/50"
    },
    {
      name: "Converted",
      value: statsData.converted.toString(),
      change: "+0%",
      icon: CheckCircle,
      gradient: "from-purple-500 to-pink-500",
      glow: "shadow-purple-500/50"
    },
    {
      name: "Follow-up",
      value: statsData.follow_up.toString(),
      change: "+0%",
      icon: AlertCircle,
      gradient: "from-orange-500 to-red-500",
      glow: "shadow-orange-500/50"
    },
  ];

  return (
    <div className="space-y-8 pb-8">
      {/* Hero Header */}
      <div className="relative overflow-hidden rounded-3xl glass p-8 border border-white/40 dark:border-white/10">
        <div className="absolute inset-0 bg-gradient-to-r from-violet-600/10 via-blue-600/10 to-purple-600/10 dark:from-violet-900/20 dark:via-blue-900/20 dark:to-purple-900/20" />
        <div className="relative z-10">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold tracking-tight">
                <span className="gradient-text">Dashboard</span>
              </h1>
              <p className="mt-2 text-slate-600 dark:text-slate-300 font-medium">
                Welcome back, {user?.first_name || user?.username || 'User'}! Here's what's happening with your sales today.
              </p>
            </div>
            <div className="hidden md:flex items-center space-x-2 glass rounded-2xl px-6 py-3 border border-white/40 dark:border-white/10">
              <Activity className="h-5 w-5 text-green-500 animate-pulse" />
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400 font-medium">System Status</p>
                <p className="text-sm font-bold text-slate-700 dark:text-slate-200">All Systems Operational</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, index) => (
          <div
            key={stat.name}
            style={{ animationDelay: `${index * 100} ms` }}
            className="group relative overflow-hidden rounded-2xl glass p-6 border border-white/40 dark:border-white/10 hover:scale-105 transition-all duration-500 cursor-pointer"
          >
            {/* Gradient Background on Hover */}
            <div className={clsx(
              "absolute inset-0 bg-gradient-to-br opacity-0 group-hover:opacity-10 transition-opacity duration-500",
              stat.gradient
            )} />

            <div className="relative z-10">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    {stat.name}
                  </p>
                  <p className="mt-3 text-4xl font-bold text-slate-900 dark:text-white">
                    {loading ? "..." : stat.value}
                  </p>
                  <div className="mt-2 flex items-center space-x-1">
                    <TrendingUp className="h-4 w-4 text-green-500" />
                    <span className="text-sm font-semibold text-green-600 dark:text-green-400">{stat.change}</span>
                    <span className="text-xs text-slate-400 dark:text-slate-500">vs last week</span>
                  </div>
                </div>

                {/* Icon with Gradient */}
                <div className={clsx(
                  "flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br shadow-lg transition-transform group-hover:scale-110 group-hover:rotate-6",
                  stat.gradient,
                  stat.glow
                )}>
                  <stat.icon className="h-7 w-7 text-white" />
                </div>
              </div>
            </div>

            {/* Bottom Glow Effect */}
            <div className={clsx(
              "absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r opacity-0 group-hover:opacity-100 transition-opacity duration-500",
              stat.gradient
            )} />
          </div>
        ))}
      </div>

      {/* Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Recent Activity</h2>
            <button
              onClick={() => router.push('/leads')}
              className="text-sm font-semibold text-violet-600 dark:text-violet-400 hover:text-violet-700 dark:hover:text-violet-300 transition-colors"
            >
              View All →
            </button>
          </div>

          <div className="space-y-4">
            {loading ? (
              <p className="text-center text-slate-500 dark:text-slate-400 py-4">Loading activity...</p>
            ) : activities.length === 0 ? (
              <p className="text-center text-slate-500 dark:text-slate-400 py-4">No recent activity.</p>
            ) : (
              activities.map((activity, index) => (
                <div
                  key={index}
                  className="group flex items-center justify-between rounded-xl glass p-4 border border-white/30 dark:border-white/5 hover:shadow-lg hover:scale-[1.02] transition-all duration-300"
                >
                  <div className="flex items-center space-x-4">
                    <div className={clsx(
                      "flex h-10 w-10 items-center justify-center rounded-xl",
                      activity.status === "success" && "bg-gradient-to-br from-green-400 to-emerald-600",
                      activity.status === "new" && "bg-gradient-to-br from-blue-400 to-cyan-600",
                      activity.status === "pending" && "bg-gradient-to-br from-orange-400 to-yellow-600"
                    )}>
                      <div className="h-2 w-2 rounded-full bg-white" />
                    </div>
                    <div>
                      <p className="font-semibold text-slate-900 dark:text-slate-100">{activity.title}</p>
                      <p className="text-sm text-slate-500 dark:text-slate-400">{activity.subtitle}</p>
                    </div>
                  </div>
                  <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">{activity.time}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
          <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-4">Quick Actions</h3>
          <div className="space-y-3">
            <button
              onClick={() => router.push('/leads')}
              className="w-full rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/50 hover:shadow-xl hover:scale-105 transition-all duration-300"
            >
              + New Lead
            </button>
            <button
              onClick={() => router.push('/leads')}
              className="w-full rounded-xl bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm px-4 py-3 text-sm font-semibold text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-white/10 hover:bg-white/90 dark:hover:bg-slate-800/80 hover:scale-105 transition-all duration-300"
            >
              📞 Make Call
            </button>
            <button
              onClick={() => router.refresh()}
              className="w-full rounded-xl bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm px-4 py-3 text-sm font-semibold text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-white/10 hover:bg-white/90 dark:hover:bg-slate-800/80 hover:scale-105 transition-all duration-300"
            >
              📊 View Reports
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
