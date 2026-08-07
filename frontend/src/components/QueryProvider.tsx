"use client";

import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";

function makeQueryClient() {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // 401s are handled by session-timeout flows; don't double-toast them
        if (error instanceof ApiError && error.status === 401) return;
        const msg = error instanceof Error ? error.message : "Failed to load data";
        // id deduplicates concurrent failures into one toast
        toast.error(msg, { id: "query-error" });
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        if (error instanceof ApiError && error.status === 401) return;
        const msg = error instanceof Error ? error.message : "Something went wrong";
        toast.error(msg);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status < 500) return false;
          return failureCount < 1;
        },
      },
      mutations: { retry: 0 },
    },
  });
}

export default function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
