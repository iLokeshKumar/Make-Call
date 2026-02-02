"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Users, Phone, Settings, Sparkles, Package } from "lucide-react";
import clsx from "clsx";

const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Leads", href: "/leads", icon: Users },
  { name: "Inventory", href: "/inventory", icon: Package },
  { name: "Calls", href: "/calls", icon: Phone },
  { name: "Settings", href: "/settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex h-screen w-72 flex-col glass border-r border-white/30 dark:border-white/10 relative overflow-hidden">
      {/* Animated Background Gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-violet-500/5 via-blue-500/5 to-purple-500/5 animate-pulse opacity-50 dark:opacity-30" />

      {/* Header */}
      <div className="relative flex h-24 items-center justify-center border-b border-white/20 dark:border-white/10 px-6">
        <div className="flex items-center space-x-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50">
            <Sparkles className="h-6 w-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              <span className="gradient-text">Rio</span>
              <span className="text-slate-700 dark:text-slate-200 ml-1">CRM</span>
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 font-medium">AI Sales Assistant</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="relative flex-1 space-y-2 p-4">
        {navItems.map((item, index) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              style={{ animationDelay: `${index * 50}ms` }}
              className={clsx(
                "group flex items-center space-x-3 rounded-xl px-4 py-3.5 text-sm font-semibold transition-all duration-300 relative overflow-hidden",
                isActive
                  ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-lg shadow-violet-500/50 scale-105"
                  : "text-slate-600 dark:text-slate-400 hover:bg-white/60 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-slate-100 hover:scale-105 hover:shadow-md"
              )}
            >
              {/* Hover Effect Gradient */}
              {!isActive && (
                <div className="absolute inset-0 bg-gradient-to-r from-violet-600/0 via-blue-600/0 to-violet-600/0 group-hover:from-violet-600/10 group-hover:via-blue-600/10 group-hover:to-violet-600/10 transition-all duration-500" />
              )}

              <item.icon className={clsx(
                "h-5 w-5 relative z-10 transition-transform group-hover:scale-110",
                isActive ? "text-white" : "text-slate-400 dark:text-slate-500 group-hover:text-violet-600 dark:group-hover:text-violet-400"
              )} />
              <span className="relative z-10">{item.name}</span>

              {/* Active Indicator */}
              {isActive && (
                <div className="absolute right-3 h-2 w-2 rounded-full bg-white animate-pulse" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer Badge */}
      <div className="relative p-4 border-t border-white/20 dark:border-white/10">
        <div className="rounded-xl bg-gradient-to-br from-violet-500/10 to-blue-500/10 p-4 border border-violet-200/50 dark:border-violet-500/20">
          <div className="flex items-center space-x-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-green-400 to-emerald-600">
              <div className="h-2 w-2 rounded-full bg-white animate-pulse" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">System Online</p>
              <p className="text-[10px] text-slate-500 dark:text-slate-500">All services active</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
