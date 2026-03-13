"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { useRouter } from "next/navigation";

interface User {
    username: string;
    email: string;
    role: "admin" | "sales_rep";
    mfa_enabled: boolean;
    is_active: boolean;
    email_verified: boolean;
    first_name?: string;
    last_name?: string;
    phone_number?: string;
    profile_picture_url?: string;
    company_name?: string;
    company_website?: string;
    google_account_email?: string;
}

export interface GoogleStatus {
    status: "valid" | "expiring_soon" | "expired" | "disconnected";
    email: string | null;
    expiry: string | null;
    message: string;
}

interface AuthContextType {
    user: User | null;
    token: string | null;
    googleStatus: GoogleStatus | null;
    login: (token: string) => void;
    logout: () => void;
    refreshUser: () => Promise<void>;
    refreshGoogleStatus: () => Promise<void>;
    isLoading: boolean;
    isSessionExpired: boolean;
    sessionTimeout: () => void;
    showPersonalDetails: boolean;
    revealPersonalDetails: () => void;
    hidePersonalDetails: () => void;
    timeLeft: number;
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    token: null,
    googleStatus: null,
    login: () => { },
    logout: () => { },
    refreshUser: async () => { },
    refreshGoogleStatus: async () => { },
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
    const [token, setToken] = useState<string | null>(null);
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

    const revealPersonalDetails = () => {
        setShowPersonalDetails(true);
        setTimeLeft(REVEAL_DURATION);
    };

    const hidePersonalDetails = () => {
        setShowPersonalDetails(false);
        setTimeLeft(0);
    };

    useEffect(() => {
        // Load token from localStorage on init
        const storedToken = localStorage.getItem("token");
        if (storedToken && storedToken.split('.').length === 3) {
            setToken(storedToken);
            fetchUser(storedToken);
        } else {
            if (storedToken) localStorage.removeItem("token");
            setIsLoading(false);
        }
    }, []);

    const fetchUser = async (authToken: string) => {
        try {
            const res = await fetch("http://localhost:6060/users/me", {
                headers: { Authorization: `Bearer ${authToken}` },
            });
            if (res.ok) {
                const userData = await res.json();
                setUser(userData);
            } else if (res.status === 401) {
                sessionTimeout();
            } else {
                logout(); // Other error
            }
        } catch (err) {
            console.error("Failed to fetch user:", err);
            logout();
        } finally {
            setIsLoading(false);
        }
    };

    const login = (authToken: string) => {
        if (!authToken || authToken.split('.').length !== 3) {
            console.error("Invalid token received during login");
            return;
        }
        localStorage.setItem("token", authToken);
        setToken(authToken);
        setIsSessionExpired(false);
        fetchUser(authToken);
        router.push("/");
    };

    const logout = () => {
        localStorage.removeItem("token");
        setToken(null);
        setUser(null);
        setIsSessionExpired(false);
        router.push("/login");
    };

    const sessionTimeout = () => {
        setIsSessionExpired(true);
        // We don't call logout() here yet, we wait for the user to click OK
    };

    const refreshUser = async () => {
        if (token) {
            await fetchUser(token);
            await refreshGoogleStatus();
        }
    };

    const refreshGoogleStatus = async () => {
        if (!token) return;
        try {
            const res = await fetch("http://localhost:6060/auth/google/status", {
                headers: { Authorization: `Bearer ${token}` },
            });
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
            user, token, googleStatus, login, logout, refreshUser, refreshGoogleStatus, isLoading, isSessionExpired, sessionTimeout,
            showPersonalDetails, revealPersonalDetails, hidePersonalDetails, timeLeft
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
