"use client";

import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/Sidebar";
import { useEffect } from "react";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    const { user, isLoading } = useAuth();
    const router = useRouter();

    const isAuthPage = pathname === "/login" || pathname === "/register";

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
        return <>{children}</>;
    }

    return (
        <div className="flex h-full w-full">
            <Sidebar />
            <main className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
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
