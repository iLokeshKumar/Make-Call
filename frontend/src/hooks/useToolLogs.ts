import { useQuery } from "@tanstack/react-query";
import { getToolLogs, getToolLogsSummary, type ToolLogsParams } from "@/lib/api";

export function useToolLogs(params: ToolLogsParams) {
  return useQuery({
    queryKey: ["tool-logs", params],
    queryFn: () => getToolLogs(params),
    select: (data) => data.logs,
    staleTime: 30_000,
  });
}

export function useToolLogsSummary(lookback_days: number) {
  return useQuery({
    queryKey: ["tool-logs-summary", lookback_days],
    queryFn: () => getToolLogsSummary(lookback_days),
    select: (data) => data.summary,
    staleTime: 30_000,
  });
}
