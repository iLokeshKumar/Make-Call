"use client";

import { useEffect, useState, Suspense, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2, ArrowRight } from "lucide-react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type VerificationResponse = {
    detail?: string | { message?: string };
    message?: string;
    status?: string;
};

function getResponseMessage(data: VerificationResponse, fallback: string) {
    if (typeof data.message === "string" && data.message.trim()) return data.message;
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
    if (data.detail?.message?.trim()) return data.detail.message;
    return fallback;
}

function VerifyContent() {
    const searchParams = useSearchParams();
    const token = searchParams.get("token");
    const [status, setStatus] = useState<"loading" | "success" | "error">(token ? "loading" : "error");
    const [message, setMessage] = useState(token ? "" : "Invalid or missing verification token.");
    const hasCalled = useRef(false);

    useEffect(() => {
        if (!token || hasCalled.current) return;

        hasCalled.current = true;

        const verifyEmail = async () => {
            try {
                const res = await fetch(`${API_BASE}/auth/verify-email?token=${encodeURIComponent(token)}`);
                const data = await res.json().catch(() => ({} as VerificationResponse));

                if (res.ok) {
                    setStatus("success");
                    setMessage(getResponseMessage(data, "Email verified successfully. You can now sign in."));
                } else {
                    setStatus("error");
                    setMessage(getResponseMessage(data, "Verification failed. Please request a new verification link."));
                }
            } catch {
                setStatus("error");
                setMessage("Could not verify your email right now. Please check your connection and try again.");
            }
        };

        verifyEmail();
    }, [token]);

    return (
        <div className="flex flex-col items-center justify-center space-y-8 text-center">
            {status === "loading" && (
                <div className="space-y-4">
                    <Loader2 className="h-16 w-16 text-violet-500 animate-spin mx-auto" />
                    <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Verifying your email...</h1>
                    <p className="text-gray-500 dark:text-gray-400">Please wait a moment while we confirm your account.</p>
                </div>
            )}

            {status === "success" && (
                <div className="space-y-6 animate-in fade-in zoom-in duration-500">
                    <div className="h-20 w-20 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
                        <CheckCircle className="h-12 w-12 text-green-500" />
                    </div>
                    <div className="space-y-2">
                        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Email verified successfully</h1>
                        <p className="text-gray-500 dark:text-gray-400">{message}</p>
                    </div>
                    <Link
                        href="/login"
                        className="inline-flex items-center px-6 py-3 bg-gradient-to-r from-violet-600 to-blue-600 text-white rounded-xl font-bold shadow-lg shadow-violet-500/20 hover:scale-105 transition-all group"
                    >
                        Go to Login
                        <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Link>
                </div>
            )}

            {status === "error" && (
                <div className="space-y-6 animate-in fade-in zoom-in duration-500">
                    <div className="h-20 w-20 bg-red-500/10 rounded-full flex items-center justify-center mx-auto">
                        <XCircle className="h-12 w-12 text-red-500" />
                    </div>
                    <div className="space-y-2">
                        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Email verification failed</h1>
                        <p className="text-gray-500 dark:text-gray-400">{message}</p>
                    </div>
                    <div className="flex flex-col space-y-3">
                        <Link
                            href="/register"
                            className="text-violet-500 hover:underline font-medium"
                        >
                            Try registering again
                        </Link>
                        <Link
                            href="/login"
                            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                        >
                            Back to login
                        </Link>
                    </div>
                </div>
            )}
        </div>
    );
}

export default function VerifyPage() {
    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-slate-900 p-4">
            <div className="max-w-md w-full glass p-10 rounded-3xl border border-white/20 shadow-2xl">
                <Suspense fallback={<Loader2 className="h-12 w-12 text-violet-500 animate-spin mx-auto" />}>
                    <VerifyContent />
                </Suspense>
            </div>
        </div>
    );
}
