"use client";

import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import Link from "next/link";

export default function LoginPage() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [mfaRequired, setMfaRequired] = useState(false);
    const [mfaToken, setMfaToken] = useState("");
    const [unverified, setUnverified] = useState(false);
    const [successMessage, setSuccessMessage] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const { login } = useAuth();

    const handleResend = async () => {
        setIsLoading(true);
        setError("");
        setSuccessMessage("");
        try {
            const res = await fetch("http://localhost:6060/auth/resend-verification", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username }),
            });
            const data = await res.json();
            if (res.ok) {
                setSuccessMessage(data.message || "A new verification link has been sent to your email.");
            } else {
                setError(data.detail || "Failed to resend link.");
            }
        } catch (err) {
            setError("Failed to resend link.");
        } finally {
            setIsLoading(false);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        setUnverified(false);
        setSuccessMessage("");
        setIsLoading(true);

        try {
            const formData = new URLSearchParams();
            formData.append("username", username);
            formData.append("password", password);

            const url = new URL("http://localhost:6060/token");
            if (mfaRequired && mfaToken) {
                url.searchParams.append("mfa_token", mfaToken);
            }

            const res = await fetch(url.toString(), {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                if (res.status === 403 && data.detail === "MFA_REQUIRED") {
                    setMfaRequired(true);
                    return;
                }
                if (res.status === 403 && data.detail === "EMAIL_UNVERIFIED") {
                    setError("Please verify your email before logging in.");
                    setUnverified(true);
                    return;
                }
                throw new Error(data.detail || "Invalid username or password");
            }

            login(data.access_token);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex items-center justify-center min-h-[80vh]">
            <div className="w-full max-w-md p-8 space-y-6 bg-white rounded-lg shadow-md dark:bg-gray-800">
                <h1 className="text-2xl font-bold text-center text-gray-900 dark:text-gray-100">
                    {mfaRequired ? "MFA Verification" : "Sign in to Rio CRM"}
                </h1>
                {error && (
                    <div className="p-3 text-sm text-red-500 bg-red-100 rounded dark:bg-red-900/30">
                        {error}
                        {unverified && (
                            <button
                                onClick={handleResend}
                                disabled={isLoading}
                                className="ml-2 underline font-bold hover:text-red-700 disabled:opacity-50"
                            >
                                Resend Link
                            </button>
                        )}
                    </div>
                )}
                {successMessage && (
                    <div className="p-3 text-sm text-green-500 bg-green-100 rounded dark:bg-green-900/30">
                        {successMessage}
                    </div>
                )}
                <form onSubmit={handleSubmit} className="space-y-4">
                    {!mfaRequired ? (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Username
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    className="w-full px-3 py-2 mt-1 border rounded-md dark:bg-gray-700 dark:border-gray-600 focus:ring-blue-500 focus:border-blue-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Password
                                </label>
                                <input
                                    type="password"
                                    required
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="w-full px-3 py-2 mt-1 border rounded-md dark:bg-gray-700 dark:border-gray-600 focus:ring-blue-500 focus:border-blue-500"
                                />
                            </div>
                        </>
                    ) : (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                                6-Digit Authenticator Code
                            </label>
                            <input
                                type="text"
                                required
                                maxLength={6}
                                value={mfaToken}
                                onChange={(e) => setMfaToken(e.target.value)}
                                className="w-full px-3 py-2 mt-1 border rounded-md dark:bg-gray-700 dark:border-gray-600 focus:ring-blue-500 focus:border-blue-500 text-center text-2xl tracking-[0.5em] font-mono"
                                placeholder="000000"
                                autoFocus
                            />
                        </div>
                    )}
                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full py-2 text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 font-bold flex items-center justify-center disabled:opacity-50"
                    >
                        {isLoading ? (
                            <div className="h-5 w-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            mfaRequired ? "Verify & Sign In" : "Sign In"
                        )}
                    </button>
                    {mfaRequired && (
                        <button
                            type="button"
                            onClick={() => setMfaRequired(false)}
                            className="w-full text-sm text-blue-600 hover:underline"
                        >
                            Back to Login
                        </button>
                    )}
                </form>
                <p className="text-sm text-center text-gray-600 dark:text-gray-400">
                    Don't have an account?{" "}
                    <Link href="/register" className="text-blue-600 hover:underline">
                        Sign up
                    </Link>
                </p>
            </div>
        </div>
    );
}
