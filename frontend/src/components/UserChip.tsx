"use client";
import React, { useState, useRef, useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/components/ThemeProvider";
import { useRouter } from "next/navigation";
import Link from "next/link";

export default function UserChip() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [showLite, setShowLite] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, []);

  if (!user) return null;

  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
  const displayName = fullName || user.email || "User";
  const initial = displayName[0].toUpperCase();

  return (
    <div className="relative hidden sm:block">
      <div className="flex items-center gap-2.5">
        <Link href="/profile" className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-slate-100 dark:bg-slate-800 flex-shrink-0 hover:shadow-sm transition">
          <div className="h-9 w-9 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white text-sm font-bold flex-shrink-0 overflow-hidden">
            {user.profile_picture_url
              ? <img src={user.profile_picture_url} alt={displayName} className="h-full w-full object-cover" />
              : initial}
          </div>
          <div className="leading-tight text-left">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{displayName}</p>
            <p className="text-[12px] text-slate-400">{user.role ? user.role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : ""}</p>
          </div>
        </Link>

        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label="Toggle theme"
          className="relative inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-600 shadow-sm transition hover:scale-[1.03] hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          <span className="absolute inset-0 rounded-full bg-yellow-400 opacity-0 transition-opacity duration-300" style={{ opacity: theme === "light" ? 1 : 0 }} />
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            className={`h-5 w-5 transition-transform duration-300 ${theme === "dark" ? "rotate-90" : "rotate-0"}`}
            fill="none"
            stroke="currentColor"
          >
            {theme === "dark" ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12.79A9 9 0 1111.21 3a7 7 0 109.79 9.79z" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v2m0 14v2m9-9h-2M5 12H3m15.364-6.364l-1.414 1.414M7.05 16.95l-1.414 1.414M16.95 16.95l-1.414-1.414M7.05 7.05L5.636 5.636M12 8a4 4 0 100 8 4 4 0 000-8z" />
            )}
          </svg>
        </button>

        <div ref={menuRef} className="relative">
          <button
            aria-haspopup="true"
            aria-expanded={open}
            onClick={() => setOpen((s) => !s)}
            className="p-1 rounded-full hover:bg-slate-200 dark:hover:bg-slate-700"
            title="Open user menu"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-slate-600 dark:text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>

          {open && (
            <div className="absolute right-0 mt-3 w-56 bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl shadow-2xl z-50 overflow-hidden">
              <div className="px-2 py-2">
                <button
                  onClick={() => { setOpen(false); router.push('/profile'); }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800 transition"
                >
                  Profile
                </button>
                <button
                  onClick={() => { setOpen(false); router.push('/settings'); }}
                  className="mt-1 w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800 transition"
                >
                  Settings
                </button>
                <button
                  onClick={() => { setOpen(false); logout(); }}
                  className="mt-1 w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-rose-600 hover:bg-rose-50 dark:hover:bg-slate-800 transition"
                >
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
