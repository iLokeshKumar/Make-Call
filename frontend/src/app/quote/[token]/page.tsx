"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type QuoteInfo = {
  quote: {
    id: number;
    quote_number: string;
    status: string;
    currency: string;
    total_amount: string;
    valid_until?: string;
    notes?: string | null;
    lead_name?: string | null;
    lead_email?: string | null;
  };
  timeline: { label: string; timestamp: string }[];
  events: { event_type: string; channel?: string | null; payload?: Record<string, unknown>; created_at: string }[];
};

const STATUS_TONE: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  accepted: "default",
  rejected: "destructive",
  negotiation: "secondary",
  sent: "default",
  draft: "secondary",
  pending: "outline",
  expired: "outline",
};

export default function QuotePublicPage() {
  const params = useParams();
  const token = params?.token as string;
  const qc = useQueryClient();

  const query = useQuery<QuoteInfo>({
    queryKey: ["quote-legacy", token],
    enabled: !!token,
    retry: false,
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/tracking/quote/info/${token}`);
      if (!res.ok) throw new Error("Quote not found");
      return res.json();
    },
  });

  const actionMut = useMutation({
    mutationFn: async (action: "accept" | "reject") => {
      const res = await fetch(`${API_BASE}/tracking/quote/${action}/${token}`, { method: "POST" });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload.detail || "Unexpected response");
      return payload;
    },
    onSuccess: (payload) => {
      toast.success(`Quote ${payload.status}`);
      qc.invalidateQueries({ queryKey: ["quote-legacy", token] });
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Action failed"),
  });

  if (query.isLoading) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
        <Card className="w-full max-w-sm text-center">
          <CardContent className="space-y-2 pt-8">
            <XCircle className="mx-auto h-10 w-10 text-red-400" />
            <p className="font-medium text-slate-700 dark:text-slate-200">
              {query.error instanceof Error ? query.error.message : "Quote cannot be found."}
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">Please verify the link.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { quote, timeline, events } = query.data;
  const isFinalized = ["accepted", "rejected"].includes(quote.status);
  const statusTone = STATUS_TONE[quote.status] ?? "secondary";

  return (
    <div className="min-h-screen w-full bg-slate-50 px-4 py-12 dark:bg-gradient-to-b dark:from-slate-950 dark:via-slate-900 dark:to-slate-950">
      <div className="mx-auto max-w-3xl space-y-6">
        <Card className="border-slate-200 dark:border-white/10 dark:bg-white/5 dark:backdrop-blur">
          <CardContent className="space-y-6 pt-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 text-lg font-bold text-white">
                R
              </div>
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-300">Rio CRM</p>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{quote.quote_number}</h1>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-slate-100/40 p-4 dark:border-white/10 dark:bg-white/10">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-300">Total</p>
                <p className="mt-2 text-3xl font-semibold text-slate-900 dark:text-white">
                  {quote.currency} {quote.total_amount}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-300">
                  Valid until {quote.valid_until ? new Date(quote.valid_until).toLocaleDateString() : "—"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-100/40 p-4 dark:border-white/10 dark:bg-white/10">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-300">Buyer</p>
                <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-white">{quote.lead_name || "Valued customer"}</p>
                <p className="text-sm text-slate-500 dark:text-slate-300">{quote.lead_email || "Email not available"}</p>
                {quote.notes && <p className="mt-2 text-sm text-slate-700 dark:text-slate-100">{quote.notes}</p>}
              </div>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Quote status</h2>
                <Badge variant={statusTone}>{quote.status.replace(/_/g, " ")}</Badge>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  onClick={() => actionMut.mutate("accept")}
                  disabled={isFinalized || actionMut.isPending}
                  className="rounded-2xl bg-emerald-500 text-sm font-semibold hover:bg-emerald-600"
                >
                  {actionMut.isPending && actionMut.variables === "accept" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                  )}
                  Accept
                </Button>
                <Button
                  variant="outline"
                  onClick={() => actionMut.mutate("reject")}
                  disabled={isFinalized || actionMut.isPending}
                  className="rounded-2xl border-red-200 text-sm font-semibold text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:text-red-300 dark:hover:bg-red-500/10"
                >
                  {actionMut.isPending && actionMut.variables === "reject" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="mr-2 h-4 w-4" />
                  )}
                  Reject
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200 dark:border-white/10 dark:bg-white/5">
          <CardContent className="space-y-3 pt-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-300">Timeline</h3>
            {timeline.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-300">No timeline available yet.</p>}
            <ul className="space-y-2">
              {timeline.map((entry) => (
                <li
                  key={`${entry.label}-${entry.timestamp}`}
                  className="flex items-center justify-between text-sm text-slate-700 dark:text-slate-200"
                >
                  <span>{entry.label}</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">{new Date(entry.timestamp).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card className="border-slate-200 dark:border-white/10 dark:bg-white/5">
          <CardContent className="space-y-3 pt-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-300">Engagement events</h3>
            {events.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-300">No tracked events yet.</p>}
            <div className="grid gap-3">
              {events.map((event) => (
                <div
                  key={event.created_at + event.event_type}
                  className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-white/10 dark:bg-white/10 dark:text-slate-200"
                >
                  <p className="font-semibold">{event.event_type}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{new Date(event.created_at).toLocaleString()}</p>
                  {event.channel && <p className="text-xs text-slate-500 dark:text-slate-400">Channel: {event.channel}</p>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
