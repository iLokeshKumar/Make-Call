"use client";

import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/Sidebar";
import { useEffect } from "react";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    const { user, isLoading, isSessionExpired, logout } = useAuth();
    const router = useRouter();

    const isAuthPage =
        pathname === "/login" ||
        pathname === "/register" ||
        pathname === "/verify" ||
        pathname === "/auth/verify-email" ||
        pathname === "/invite/accept" ||
        pathname.startsWith("/q/") ||         // public quote view
        pathname.startsWith("/quote/") ||     // legacy public quote view
        pathname.startsWith("/feedback/");    // public CSAT feedback

    useEffect(() => {
        if (!isLoading && !user && !isAuthPage) {
            router.push("/login");
        }
    }, [user, isLoading, pathname, router, isAuthPage]);

    if (isLoading && !isAuthPage) {
        return (
            <div className="flex h-screen w-full items-center justify-center bg-slate-900">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-violet-500"></div>
            </div>
        );
    }

    if (isAuthPage) {
        // Body is flex/overflow-hidden for the CRM shell; public pages need their
        // own scroll container so forms and quote screens longer than the viewport
        // aren't clipped.
        return <div className="h-screen w-full overflow-y-auto">{children}</div>;
    }

    return (
        <div className="flex h-full w-full relative">
            {/* Session Timeout Dark Overlay Modal */}
            {isSessionExpired && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-950/80 backdrop-blur-md transition-all duration-500 animate-in fade-in">
                    <div className="max-w-md w-full mx-4 bg-white dark:bg-slate-900 rounded-3xl shadow-2xl border border-slate-200 dark:border-slate-800 p-8 transform transition-all animate-in zoom-in-95 duration-300">
                        <div className="flex flex-col items-center text-center">
                            <div className="h-20 w-20 rounded-full bg-violet-500/10 flex items-center justify-center mb-6">
                                <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 text-violet-600 dark:text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m0 0v2m0-2h2m-2 0H10m4-6a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                                </svg>
                            </div>
                            <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">Session Timed Out</h2>
                            <p className="text-slate-600 dark:text-slate-400 mb-8 leading-relaxed">
                                For your security, your session has expired. Please log in again to continue managing your CRM.
                            </p>
                            <button
                                onClick={logout}
                                className="w-full py-4 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 text-white font-bold rounded-2xl shadow-lg shadow-violet-500/25 transition-all transform hover:scale-[1.02] active:scale-[0.98]"
                            >
                                OK, Log Me Out
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <Sidebar />
            <main className="flex-1 overflow-y-auto bg-gradient-to-br from-slate-50 via-violet-50/40 to-blue-50/30 dark:from-slate-900 dark:via-slate-900 dark:to-slate-900">
                {!user?.email_verified && user && (
                    <div className="bg-amber-500/10 border-b border-amber-500/20 px-8 py-3 flex items-center justify-between">
                        <div className="flex items-center space-x-3 text-amber-600 dark:text-amber-400 font-medium">
                            <div className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                            <span>Your email is not verified. Some features may be restricted.</span>
                        </div>
                        <button className="text-sm font-bold text-amber-600 dark:text-amber-400 hover:underline">
                            Resend Link
                        </button>
                    </div>
                )}
                <div className="p-8">
                    {children}
                </div>
            </main>
        </div>
    );
}
