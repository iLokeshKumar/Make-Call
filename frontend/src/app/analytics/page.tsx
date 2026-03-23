"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import AnalyticsDashboard from "../../components/AnalyticsDashboard";

export default function AnalyticsPage() {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !token) {
      router.push("/login");
    }
  }, [token, isLoading, router]);

  if (isLoading || !token) {
    return null; // Or a loading spinner
  }

  return (
    <main className="p-8 max-w-7xl mx-auto">
      <AnalyticsDashboard />
    </main>
  );
}