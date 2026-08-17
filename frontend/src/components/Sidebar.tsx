"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Users, Phone, Settings, Sparkles, Package, LogOut, Activity,
  ChevronLeft, ChevronRight, User as UserIcon, Mail, Smartphone, Eye, EyeOff, ShieldCheck, X, Loader2, Clock, UserCog, Building2, Megaphone,
  FileText, Layout, Cpu, BookOpen, LayoutGrid, MessageSquare, Database, Bot,
  ShoppingCart, Receipt, CreditCard, Ticket, Wrench, UserCheck, ClipboardCheck
} from "lucide-react";
import clsx from "clsx";
import { useAuth } from "@/context/AuthContext";
import { maskEmail, maskPhone } from "@/utils/security";
import { useRecentlyViewed } from "@/hooks/useRecentlyViewed";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";
const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Leads", href: "/leads", icon: Users },
  { name: "Campaigns", href: "/campaigns", icon: Megaphone },
  { name: "Calls", href: "/calls", icon: Phone },
  { name: "Voice Agent", href: "/voice-agents", icon: Sparkles },
  { name: "Inventory", href: "/inventory", icon: Package, adminOnly: true },
  { name: "Analytics", href: "/analytics", icon: Activity },
  { name: "Evaluations", href: "/evals", icon: ClipboardCheck, adminOnly: true },
  { name: "Quotes", href: "/quotes", icon: FileText },
  { name: "Accounts", href: "/accounts", icon: Building2 },
  { name: "Templates", href: "/templates", icon: Layout, adminOnly: true },
  { name: "Automation", href: "/automation", icon: Cpu, adminOnly: true },
  { name: "Kanban", href: "/leads/kanban", icon: LayoutGrid },
  { name: "Feedback", href: "/feedback", icon: MessageSquare },
  { name: "Objections", href: "/objections", icon: BookOpen },
  { name: "Knowledge", href: "/knowledge", icon: Database },
  { name: "Orders", href: "/orders", icon: ShoppingCart },
  { name: "Invoices", href: "/invoices", icon: Receipt },
  { name: "Payments", href: "/payments", icon: CreditCard },
  { name: "Tickets", href: "/tickets", icon: Ticket },
  { name: "Installations", href: "/installations", icon: Wrench },
  { name: "Contacts", href: "/contacts", icon: UserCheck },
  { name: "Agent Tasks", href: "/agent-tasks", icon: Bot },
  { name: "Activity", href: "/agents/activity", icon: Activity },
  { name: "Admin", href: "/admin", icon: ShieldCheck, adminOnly: true },
  { name: "Profile", href: "/profile", icon: UserCog },
  { name: "Company", href: "/company-profile", icon: Building2, adminOnly: true },
  { name: "Settings", href: "/settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout, showPersonalDetails, revealPersonalDetails, hidePersonalDetails, timeLeft } = useAuth();
  
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Resizing State
  const [sidebarWidth, setSidebarWidth] = useState(288); // Default w-72 = 288px
  const [isResizing, setIsResizing] = useState(false);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const stopResizing = useCallback(() => {
    setIsResizing(false);
  }, []);

  const resize = useCallback((e: MouseEvent) => {
    if (isResizing) {
      const newWidth = e.clientX;
      if (newWidth > 80 && newWidth < 450) {
        setSidebarWidth(newWidth);
      }
    }
  }, [isResizing]);

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [resize, stopResizing]);

  // OTP Reveal State
  const [isOtpModalOpen, setIsOtpModalOpen] = useState(false);
  const [otpValue, setOtpValue] = useState("");
  const [isRequestingOtp, setIsRequestingOtp] = useState(false);
  const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);
  const [otpError, setOtpError] = useState("");

  // Timer State
  const REVEAL_DURATION = 120; // 2 minutes in seconds

  const { items: recentPages, track: trackPage } = useRecentlyViewed("rio_pages_recent", 5);

  useEffect(() => {
    const navItem = navItems.find(n => n.href === pathname);
    if (navItem) trackPage({ id: navItem.href, label: navItem.name, href: navItem.href });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const filteredItems = navItems.filter(
    (item) => !item.adminOnly || ["admin", "company_admin", "company_owner"].includes(user?.role || "")
  );

  const handleRequestReveal = async () => {
    if (showPersonalDetails) {
      hidePersonalDetails();
      return;
    }

    setIsOtpModalOpen(true);
    setIsRequestingOtp(true);
    setOtpError("");

    try {
      const res = await apiFetch(`${API_BASE}/auth/reveal/request`, {
        method: "POST"
      });
      if (!res.ok) throw new Error("Failed to send OTP");
    } catch (err) {
      setOtpError("Failed to send verification code. Please try again.");
    } finally {
      setIsRequestingOtp(false);
    }
  };

  const handleVerifyReveal = async () => {
    setIsVerifyingOtp(true);
    setOtpError("");

    try {
      const res = await apiFetch(`${API_BASE}/auth/reveal/verify`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json" },
        body: JSON.stringify({ token: otpValue }) });

      if (res.ok) {
        revealPersonalDetails();
        setIsOtpModalOpen(false);
        setOtpValue("");
      } else {
        const data = await res.json();
        setOtpError(data.detail || "Invalid code. Please try again.");
      }
    } catch (err) {
      setOtpError("Network error. Please try again.");
    } finally {
      setIsVerifyingOtp(false);
    }
  };

  return (
    <>
      <div
        className={clsx(
          "flex h-screen flex-col bg-white dark:bg-slate-900/60 border-r border-slate-200 dark:border-white/10 relative overflow-hidden transition-all duration-300 select-none",
          isResizing && "transition-none" // Disable transitions while resizing for smoothness
        )}
        style={{ width: isCollapsed ? 80 : sidebarWidth }}
      >
        {/* Animated Background Gradient */}
        <div className="absolute inset-0 bg-gradient-to-br from-violet-500/5 via-blue-500/5 to-purple-500/5 dark:from-violet-500/10 dark:via-blue-500/10 dark:to-purple-500/10 animate-pulse opacity-40 dark:opacity-30 pointer-events-none" />

        {/* Resize Handle */}
        {!isCollapsed && (
          <div
            onMouseDown={startResizing}
            className={clsx(
              "absolute top-0 right-0 z-[60] h-full w-1 cursor-col-resize transition-all hover:bg-violet-500/30",
              isResizing ? "bg-violet-500/50 w-1.5" : "bg-transparent"
            )}
          />
        )}

        {/* Collapse Toggle Button */}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="absolute -right-3 top-10 z-[70] flex h-6 w-6 items-center justify-center rounded-full bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-violet-600 dark:hover:text-white hover:border-violet-400 dark:hover:border-violet-500 transition-all duration-300 shadow-lg"
        >
          {isCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>

        {/* Header */}
        <div className={clsx(
          "relative flex h-24 items-center border-b border-slate-200 dark:border-white/10 px-6 transition-all",
          isCollapsed ? "justify-center" : "justify-start"
        )}>
          <div className="flex items-center space-x-3">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50">
              <Sparkles className="h-6 w-6 text-white" />
            </div>
            {!isCollapsed && (
              <div className="animate-in fade-in slide-in-from-left-2 duration-300">
                <h1 className="text-xl font-bold tracking-tight truncate max-w-[180px]">
                  <span className="gradient-text">{user?.company_name || ""}</span>
                  <span className="text-slate-700 dark:text-slate-200 ml-1">CRM</span>
                </h1>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-tighter">Digital Sales Representative</p>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav className="relative flex-1 space-y-2 overflow-y-auto p-4">
          {filteredItems.map((item, index) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                style={{ animationDelay: `${index * 50}ms` }}
                className={clsx(
                  "group flex items-center rounded-xl px-4 py-3.5 text-sm font-semibold transition-all duration-300 relative overflow-hidden",
                  isActive
                    ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-lg shadow-violet-500/50 scale-105"
                    : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-slate-100 hover:scale-105 hover:shadow-md",
                  isCollapsed ? "justify-center" : "space-x-3"
                )}
              >
                {/* Hover Effect Gradient */}
                {!isActive && (
                  <div className="absolute inset-0 bg-gradient-to-r from-violet-600/0 via-blue-600/0 to-violet-600/0 group-hover:from-violet-600/5 group-hover:via-blue-600/5 group-hover:to-violet-600/5 dark:group-hover:from-violet-600/10 dark:group-hover:via-blue-600/10 dark:group-hover:to-violet-600/10 transition-all duration-500" />
                )}

                <item.icon className={clsx(
                  "h-5 w-5 flex-shrink-0 relative z-10 transition-transform group-hover:scale-110",
                  isActive ? "text-white" : "text-slate-400 dark:text-slate-500 group-hover:text-violet-500 dark:group-hover:text-violet-400"
                )} />

                {!isCollapsed && (
                  <span className="relative z-10 animate-in fade-in slide-in-from-left-2 duration-300">{item.name}</span>
                )}

                {/* Active Indicator */}
                {isActive && !isCollapsed && (
                  <div className="absolute right-3 h-2 w-2 rounded-full bg-white animate-pulse" />
                )}
              </Link>
            );
          })}

          {/* Recently Viewed */}
          {recentPages.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-200 dark:border-white/10">
              {!isCollapsed && (
                <p className="flex items-center gap-1.5 px-2 mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                  <Clock size={10} /> Recent
                </p>
              )}
              {recentPages.map((item) => {
                const navItem = navItems.find(n => n.href === item.id);
                if (!navItem) return null;
                const Icon = navItem.icon;
                const isActive = pathname === item.id;
                return (
                  <Link
                    key={item.id}
                    href={item.id}
                    className={clsx(
                      "group flex items-center rounded-xl px-4 py-2.5 text-sm font-medium transition-all duration-200 relative overflow-hidden mb-1",
                      isActive
                        ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-md shadow-violet-500/30"
                        : "text-slate-500 dark:text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-700 dark:hover:text-slate-300",
                      isCollapsed ? "justify-center" : "space-x-2.5"
                    )}
                    title={isCollapsed ? item.label : undefined}
                  >
                    <Icon className={clsx(
                      "h-4 w-4 flex-shrink-0",
                      isActive ? "text-white" : "text-slate-400 dark:text-slate-600 group-hover:text-violet-500"
                    )} />
                    {!isCollapsed && (
                      <span className="truncate text-xs">{item.label}</span>
                    )}
                  </Link>
                );
              })}
            </div>
          )}
        </nav>

        {/* User Section */}
        {isCollapsed && (
          <div className="p-4 border-t border-slate-200 dark:border-white/10 flex justify-center">
            <div className="h-9 w-9 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 border border-white/10 flex items-center justify-center overflow-hidden shadow-inner flex-shrink-0">
              {user?.profile_picture_url ? (
                <img src={user.profile_picture_url} alt="Profile" className="h-full w-full object-cover" />
              ) : (
                <UserIcon size={18} className="text-white/80" />
              )}
            </div>
          </div>
        )}
        {!isCollapsed && (
          <div className="relative p-4 border-t border-slate-200 dark:border-white/10 animate-in fade-in slide-in-from-bottom-2 duration-500">
            <div className="rounded-xl bg-slate-50 dark:bg-slate-800/30 p-4 border border-slate-200 dark:border-white/5 space-y-3 relative overflow-hidden">
              {/* Countdown Progress Bar */}
              {showPersonalDetails && (
                <div
                  className="absolute top-0 left-0 h-0.5 bg-gradient-to-r from-violet-500 to-blue-500 transition-all duration-1000 ease-linear"
                  style={{ width: `${(timeLeft / REVEAL_DURATION) * 100}%` }}
                />
              )}

              <div className="flex items-center space-x-3">
                <div className="h-10 w-10 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 border border-white/10 flex items-center justify-center overflow-hidden shadow-inner">
                  {user?.profile_picture_url ? (
                    <img src={user.profile_picture_url} alt="Profile" className="h-full w-full object-cover" />
                  ) : (
                    <UserIcon size={20} className="text-white/80" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-slate-900 dark:text-white truncate">
                    {user?.first_name || 'User'} {user?.last_name || ''}
                  </p>
                  <p className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider font-bold">@{user?.username || 'rio_user'}</p>
                </div>
              </div>

              <div className="space-y-1.5 border-t border-slate-200 dark:border-slate-700 pt-3 opacity-80">
                <div className="flex items-center justify-between text-[11px] mb-1">
                  <span className="text-slate-500 dark:text-slate-400 uppercase font-bold tracking-widest flex items-center">
                    <ShieldCheck size={10} className="mr-1" /> Security
                    {showPersonalDetails && (
                      <span className="ml-2 flex items-center text-violet-500 dark:text-violet-400 animate-pulse">
                        <Clock size={8} className="mr-1" /> {Math.floor(timeLeft / 60)}:{(timeLeft % 60).toString().padStart(2, '0')}
                      </span>
                    )}
                  </span>
                  <button
                    onClick={handleRequestReveal}
                    className="text-violet-500 dark:text-violet-400 hover:text-violet-700 dark:hover:text-white transition-colors"
                  >
                    {showPersonalDetails ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <div className="flex items-center text-xs text-slate-600 dark:text-slate-300">
                  <Mail size={12} className="mr-2 text-violet-500 dark:text-violet-400" />
                  <span className="truncate">{showPersonalDetails ? (user?.email || 'user@example.com') : maskEmail(user?.email || '')}</span>
                </div>
                <div className="flex items-center text-xs text-slate-600 dark:text-slate-300">
                  <Smartphone size={12} className="mr-2 text-blue-500 dark:text-blue-400" />
                  <span>{showPersonalDetails ? (user?.phone_number || 'N/A') : maskPhone(user?.phone_number || '')}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Logout & Footer */}
        <div className="p-4 border-t border-slate-200 dark:border-white/10">
          <button
            onClick={logout}
            className={clsx(
              "group flex w-full items-center rounded-xl px-4 py-3 text-sm font-semibold text-slate-500 dark:text-slate-300 hover:bg-red-50 dark:hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-500 transition-all duration-300",
              isCollapsed ? "justify-center" : "space-x-3"
            )}
          >
            <LogOut className="h-5 w-5 flex-shrink-0 transition-transform group-hover:translate-x-1" />
            {!isCollapsed && <span>Log Out</span>}
          </button>
        </div>

        <div className="relative p-4 border-t border-slate-200 dark:border-white/10">
          <div className={clsx(
            "rounded-xl bg-gradient-to-br from-violet-50 to-blue-50 dark:from-violet-500/10 dark:to-blue-500/10 p-4 border border-violet-100 dark:border-violet-500/20",
            isCollapsed ? "flex justify-center" : ""
          )}>
            <div className="flex items-center space-x-2">
              <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-green-400 to-emerald-600">
                <div className="h-2 w-2 rounded-full bg-white animate-pulse" />
              </div>
              {!isCollapsed && (
                <div>
                  <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">System Online</p>
                  <p className="text-[10px] text-slate-500 dark:text-slate-500">All services active</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* OTP Modal */}
      {isOtpModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 dark:bg-slate-950/80 backdrop-blur-sm p-4 animate-in fade-in duration-300">
          <div className="w-full max-w-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 shadow-2xl space-y-6 relative overflow-hidden animate-in zoom-in-95 duration-300">
            {/* Modal Background Decor */}
            <div className="absolute -top-12 -right-12 h-32 w-32 bg-violet-600/10 dark:bg-violet-600/20 rounded-full blur-3xl" />

            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <ShieldCheck className="text-violet-500" />
                Identity Verification
              </h3>
              <button
                onClick={() => setIsOtpModalOpen(false)}
                className="text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors"
                disabled={isVerifyingOtp}
              >
                <X size={20} />
              </button>
            </div>

            <p className="text-sm text-slate-500 dark:text-slate-400">
              We&apos;ve sent a 6-digit verification code to <strong>{maskEmail(user?.email || '')}</strong>. Enter it below to reveal your sensitive details.
            </p>

            <div className="space-y-4">
              <div className="relative">
                <input
                  type="text"
                  maxLength={6}
                  value={otpValue}
                  onChange={(e) => setOtpValue(e.target.value.replace(/\D/g, ""))}
                  placeholder="000000"
                  className="w-full bg-slate-50 dark:bg-slate-800/50 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-3 text-center text-3xl tracking-[0.4em] font-mono text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 transition-all placeholder:text-slate-300 dark:placeholder:text-slate-600"
                  disabled={isVerifyingOtp || isRequestingOtp}
                  autoFocus
                />
                {isRequestingOtp && (
                  <div className="absolute inset-0 bg-white/50 dark:bg-slate-900/50 flex items-center justify-center rounded-xl">
                    <Loader2 className="animate-spin text-violet-500" />
                  </div>
                )}
              </div>

              {otpError && (
                <p className="text-xs text-red-500 text-center animate-in shake duration-300">{otpError}</p>
              )}

              <button
                onClick={handleVerifyReveal}
                disabled={otpValue.length !== 6 || isVerifyingOtp || isRequestingOtp}
                className="w-full py-3 bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-700 hover:to-blue-700 text-white rounded-xl font-bold transition-all disabled:opacity-50 disabled:scale-100 active:scale-95 flex items-center justify-center"
              >
                {isVerifyingOtp ? <Loader2 className="animate-spin mr-2" /> : "Verify & Reveal"}
              </button>
            </div>

            <p className="text-[10px] text-center text-slate-400 dark:text-slate-500">
              This code will expire in 10 minutes. Haven&apos;t received it? Check your spam folder.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
