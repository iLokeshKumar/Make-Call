"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Users, Phone, Settings, LogOut } from "lucide-react";
import clsx from "clsx";

const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Leads", href: "/leads", icon: Users },
  { name: "Calls", href: "/calls", icon: Phone },
  { name: "Settings", href: "/settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex h-screen w-64 flex-col bg-white border-r border-slate-200">
      <div className="flex h-20 items-center px-6 border-b border-slate-200">
        <h1 className="text-xl font-bold tracking-tight text-slate-900">Rio<span className="text-blue-600">CRM</span></h1>
      </div>
      <nav className="flex-1 space-y-1 p-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={clsx(
                "flex items-center space-x-3 rounded-md px-4 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              )}
            >
              <item.icon className={clsx("h-4 w-4", isActive ? "text-blue-600" : "text-slate-400")} />
              <span>{item.name}</span>
            </Link>
          )
        })}
      </nav>

    </div>
  );
}
