"use client";

import { Phone, Users, CheckCircle, AlertCircle } from "lucide-react";
import clsx from "clsx";

const stats = [
  { name: "Total Leads", value: "24", icon: Users, color: "text-blue-500", bg: "bg-blue-50" },
  { name: "Calls Today", value: "12", icon: Phone, color: "text-green-500", bg: "bg-green-50" },
  { name: "Converted", value: "5", icon: CheckCircle, color: "text-purple-500", bg: "bg-purple-50" },
  { name: "Follow-up", value: "3", icon: AlertCircle, color: "text-orange-500", bg: "bg-orange-50" },
];

export default function Home() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard Overview</h1>
        <p className="mt-1 text-slate-500">Welcome back, verified stats for Yexis Electronics.</p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <div key={stat.name} className="rounded-xl bg-white p-6 shadow-sm border border-slate-100">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-500">{stat.name}</p>
                <p className="mt-2 text-3xl font-bold text-slate-900 tracking-tight">{stat.value}</p>
              </div>
              <div className={clsx("rounded-lg p-3", stat.bg)}>
                <stat.icon className={clsx("h-5 w-5", stat.color)} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl bg-white p-6 border border-slate-100 max-w-2xl shadow-sm">
        <h2 className="text-lg font-bold text-slate-900 mb-4">Recent Activity</h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4 last:border-0 last:pb-0">
            <div>
              <p className="font-medium text-slate-900">Call with Alice Johnson</p>
              <p className="text-sm text-slate-500">Interested in 55 TV</p>
            </div>
            <span className="text-xs text-slate-400 font-mono">2m ago</span>
          </div>
          <div className="flex items-center justify-between border-b border-slate-100 pb-4 last:border-0 last:pb-0">
            <div>
              <p className="font-medium text-slate-900">Lead Created: Bob Smith</p>
              <p className="text-sm text-slate-500">Budget $500</p>
            </div>
            <span className="text-xs text-slate-400 font-mono">1h ago</span>
          </div>
        </div>
      </div>
    </div>
  );
}
