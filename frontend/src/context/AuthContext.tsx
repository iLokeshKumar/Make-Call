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
}

interface AuthContextType {
    user: User | null;
    token: string | null;
    login: (token: string) => void;
    logout: () => void;
    refreshUser: () => Promise<void>;
    isLoading: boolean;
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    token: null,
    login: () => { },
    logout: () => { },
    refreshUser: async () => { },
    isLoading: true,
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();

    useEffect(() => {
        // Load token from localStorage on init
        const storedToken = localStorage.getItem("token");
        if (storedToken) {
            setToken(storedToken);
            fetchUser(storedToken);
        } else {
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
            } else {
                logout(); // Invalid token
            }
        } catch (err) {
            console.error("Failed to fetch user:", err);
            logout();
        } finally {
            setIsLoading(false);
        }
    };

    const login = (authToken: string) => {
        localStorage.setItem("token", authToken);
        setToken(authToken);
        fetchUser(authToken);
        router.push("/");
    };

    const logout = () => {
        localStorage.removeItem("token");
        setToken(null);
        setUser(null);
        router.push("/login");
    };

    const refreshUser = async () => {
        if (token) await fetchUser(token);
    };

    return (
        <AuthContext.Provider value={{ user, token, login, logout, refreshUser, isLoading }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
