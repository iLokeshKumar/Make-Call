"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles, Zap } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { formatNextActionLabel } from "@/utils/interaction_format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type ExplainPayload = {
  lead_id: number;
  ism_stage: string | null;
  matched_rule: {
    id: number;
    name: string;
    priority: number;
    when_json: Record<string, unknown>;
    then_action: string;
  } | null;
  action: { verb: string; argument: string | null } | null;
};

type Props = {
  leadId: number;
  fallbackRecommendation: { next_action?: string; suggested_product?: string; follow_up_days?: number } | null;
  onSessionTimeout: () => void;
};

export default function ExplainNextAction({ leadId, fallbackRecommendation, onSessionTimeout }: Props) {
  const query = useQuery<ExplainPayload>({
    queryKey: ["explain-next-action", leadId],
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/next-action-explain`);
      if (res.status === 401) {
        onSessionTimeout();
        throw new Error("unauthorized");
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
  });

  if (query.isLoading) {
    return <p className="text-sm text-slate-500">Loading explanation...</p>;
  }
  if (query.error) {
    return <p className="text-sm text-amber-600">Could not load rule explanation.</p>;
  }
  const data = query.data;
  if (!data) return null;

  if (data.matched_rule) {
    const { matched_rule: rule, action } = data;
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-3 rounded-xl bg-violet-50 p-3 dark:bg-violet-500/10">
          <Zap className="h-4 w-4 flex-shrink-0 text-violet-600 dark:text-violet-300" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-200">Rule fired</p>
            <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">
              #{rule.id} — {rule.name}
              <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">priority {rule.priority}</span>
            </p>
            {action && (
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                Action: <span className="font-mono">{action.verb}</span>
                {action.argument && <span className="font-mono">{`(${action.argument})`}</span>}
              </p>
            )}
          </div>
        </div>
        <details className="rounded-lg border border-slate-200 p-2 text-xs dark:border-white/10">
          <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300">Rule condition</summary>
          <pre className="mt-2 overflow-x-auto text-[11px] text-slate-500 dark:text-slate-400">{JSON.stringify(rule.when_json, null, 2)}</pre>
        </details>
      </div>
    );
  }

  if (fallbackRecommendation?.next_action) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 dark:border-white/10">
        <Sparkles className="h-4 w-4 flex-shrink-0 text-blue-500" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">No rule matched — AI recommendation</p>
          <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">
            {formatNextActionLabel(fallbackRecommendation.next_action)}
            {fallbackRecommendation.suggested_product && <span className="text-slate-500 dark:text-slate-400"> — {fallbackRecommendation.suggested_product}</span>}
          </p>
          {fallbackRecommendation.follow_up_days ? (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Follow up in {fallbackRecommendation.follow_up_days} days</p>
          ) : null}
        </div>
      </div>
    );
  }

  return <p className="text-sm text-slate-500 dark:text-slate-400">No rule matched and no AI recommendation yet.</p>;
}
