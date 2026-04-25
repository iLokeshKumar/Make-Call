"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/utils/apiFetch";

interface Company {
    id: number;
    name: string;
    domain?: string;
    website?: string;
    logo_url?: string;
    primary_color: string;
    is_active: boolean;
    subscription_tier: string;
    max_users: number;
    features_enabled: string;
}

type UserRole = "company_admin" | "company_owner" | "sales_representative";

interface User {
    id: number;
    username: string;
    email: string;
    role: UserRole;
    mfa_enabled: boolean;
    is_active: boolean;
    email_verified: boolean;
    first_name?: string;
    last_name?: string;
    phone_number?: string;
    profile_picture_url?: string;
    company_id: number;
    company_name?: string;
    company_website?: string;
    google_account_email?: string;
    company?: Company;
    created_at?: string;
}

export interface GoogleStatus {
    status: "valid" | "expiring_soon" | "expired" | "disconnected";
    email: string | null;
    expiry: string | null;
    message: string;
}

interface AuthContextType {
    user: User | null;
    googleStatus: GoogleStatus | null;
    /** Mark the session as authenticated after a successful /token POST.
     * No token parameter — authentication is proven by the httpOnly cookie
     * the server set in the login response, not by any value the client holds. */
    login: () => Promise<void>;
    logout: () => void;
    refreshUser: () => Promise<void>;
    refreshGoogleStatus: () => Promise<void>;
    logoutAll: () => Promise<void>;
    isLoading: boolean;
    isSessionExpired: boolean;
    sessionTimeout: () => void;
    showPersonalDetails: boolean;
    revealPersonalDetails: () => void;
    hidePersonalDetails: () => void;
    timeLeft: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

const AuthContext = createContext<AuthContextType>({
    user: null,
    googleStatus: null,
    login: async () => { },
    logout: () => { },
    refreshUser: async () => { },
    refreshGoogleStatus: async () => { },
    logoutAll: async () => { },
    isLoading: true,
    isSessionExpired: false,
    sessionTimeout: () => { },
    showPersonalDetails: false,
    revealPersonalDetails: () => { },
    hidePersonalDetails: () => { },
    timeLeft: 0,
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null);
    const [googleStatus, setGoogleStatus] = useState<GoogleStatus | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSessionExpired, setIsSessionExpired] = useState(false);
    const [showPersonalDetails, setShowPersonalDetails] = useState(false);
    const [timeLeft, setTimeLeft] = useState(0);
    const REVEAL_DURATION = 120; // 2 minutes
    const router = useRouter();

    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (showPersonalDetails && timeLeft > 0) {
            interval = setInterval(() => {
                setTimeLeft((prev) => prev - 1);
            }, 1000);
        } else if (timeLeft === 0 && showPersonalDetails) {
            setShowPersonalDetails(false);
        }
        return () => clearInterval(interval);
    }, [showPersonalDetails, timeLeft]);

    const normalizeRole = (role?: string): UserRole => {
        if (role === "company_owner") return "company_owner";
        if (role === "company_admin") return "company_admin";
        return "sales_representative";
    };

    const fetchUser = useCallback(async () => {
        // Cookie-only — the browser sends rio_session automatically.
        // Result: 200 = logged in; 401 = not (stay silent, caller decides UX).
        try {
            const res = await apiFetch(`${API_BASE}/users/me`);
            if (res.ok) {
                const userData = await res.json();
                setUser({
                    ...userData,
                    role: normalizeRole(userData.role),
                });
            } else {
                setUser(null);
            }
        } catch (err) {
            console.error("Failed to fetch user:", err);
            setUser(null);
        }
    }, []);

    // On app mount: ask the server "who am I?" using the cookie. If valid,
    // we're logged in without the client ever touching a token.
    useEffect(() => {
        fetchUser().finally(() => setIsLoading(false));
    }, [fetchUser]);

    const revealPersonalDetails = () => {
        setShowPersonalDetails(true);
        setTimeLeft(REVEAL_DURATION);
    };

    const hidePersonalDetails = () => {
        setShowPersonalDetails(false);
        setTimeLeft(0);
    };

    const login = async () => {
        // The caller just POSTed to /token; the server set rio_session + rio_csrf
        // cookies on the response. We confirm by fetching /users/me.
        setIsSessionExpired(false);
        await fetchUser();
        router.push("/");
    };

    const logout = () => {
        // Clear server cookies (best-effort — /auth/logout is in CSRF bypass).
        fetch(`${API_BASE}/auth/logout`, {
            method: "POST",
            credentials: "include",
        }).catch(() => { /* network error: ok */ });
        setUser(null);
        setIsSessionExpired(false);
        router.push("/login");
    };

    const sessionTimeout = () => {
        setIsSessionExpired(true);
        // We don't call logout() here yet, we wait for the user to click OK
    };

    const logoutAll = async () => {
        try {
            const res = await apiFetch(`${API_BASE}/auth/logout-all`, {
                method: "POST",
            });
            if (res.ok) {
                logout();
            } else {
                console.warn("logout-all failed", await res.text());
            }
        } catch (err) {
            console.error("logout-all error", err);
        }
    };

    const refreshUser = async () => {
        await fetchUser();
        await refreshGoogleStatus();
    };

    const refreshGoogleStatus = async () => {
        try {
            const res = await apiFetch(`${API_BASE}/auth/google/status`);
            if (res.ok) {
                const status = await res.json();
                setGoogleStatus(status);
            }
        } catch (err) {
            console.error("Failed to fetch Google status:", err);
        }
    };

    return (
        <AuthContext.Provider value={{
            user, googleStatus, login, logout, logoutAll, refreshUser, refreshGoogleStatus, isLoading, isSessionExpired, sessionTimeout,
            showPersonalDetails, revealPersonalDetails, hidePersonalDetails, timeLeft
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
