import { apiFetch } from "@/utils/apiFetch";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

export const CRM_BASE = `${API_BASE}/crm`;

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseOrThrow<T>(res: Response, onUnauthorized?: () => void): Promise<T> {
  if (res.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail ?? body.message ?? message;
    } catch { /* ignore */ }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export function apiGet<T>(url: string, onUnauthorized?: () => void): Promise<T> {
  return apiFetch(url).then((res) => parseOrThrow<T>(res, onUnauthorized));
}

export function apiPost<T>(
  url: string,
  body?: unknown,
  onUnauthorized?: () => void,
): Promise<T> {
  return apiFetch(url, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then((res) => parseOrThrow<T>(res, onUnauthorized));
}

export function apiPatch<T>(
  url: string,
  body?: unknown,
  onUnauthorized?: () => void,
): Promise<T> {
  return apiFetch(url, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then((res) => parseOrThrow<T>(res, onUnauthorized));
}

export function apiDelete<T = void>(url: string, onUnauthorized?: () => void): Promise<T> {
  return apiFetch(url, { method: "DELETE" }).then((res) =>
    parseOrThrow<T>(res, onUnauthorized),
  );
}

// ─── Tool Logs ────────────────────────────────────────────────────────────────

export type ToolLogRow = {
  id: number;
  tool_name: string;
  status: "success" | "error" | "timeout";
  duration_ms: number;
  error_message: string | null;
  user_id: number | null;
  interaction_id: number | null;
  created_at: string;
};

export type ToolLogSummaryRow = {
  tool_name: string;
  total: number;
  success: number;
  error: number;
  timeout: number;
  avg_ms: number;
};

export type ToolLogsParams = {
  limit?: number;
  tool_name?: string;
  status?: string;
};

export function getToolLogs(params: ToolLogsParams = {}): Promise<{ logs: ToolLogRow[] }> {
  const qs = new URLSearchParams({ limit: String(params.limit ?? 100) });
  if (params.tool_name) qs.set("tool_name", params.tool_name);
  if (params.status) qs.set("status", params.status);
  return apiGet(`${CRM_BASE}/tool-logs?${qs}`);
}

export function getToolLogsSummary(
  lookback_days: number,
): Promise<{ summary: ToolLogSummaryRow[] }> {
  return apiGet(`${CRM_BASE}/tool-logs/summary?lookback_days=${lookback_days}`);
}

// ─── MCP Registry ─────────────────────────────────────────────────────────────

export type MCPServerRecord = {
  id: number;
  name: string;
  provider: string;
  url: string;
  transport: string;
  auth_type: string;
  capabilities_json: string[];
  enabled: boolean;
  priority: number;
  last_health_status: string | null;
};

export type MCPServerCreate = Omit<MCPServerRecord, "id" | "last_health_status">;

export function getMCPServers(): Promise<MCPServerRecord[]> {
  return apiGet(`${API_BASE}/mcp-connections/registry`);
}

export function createMCPServer(body: MCPServerCreate): Promise<MCPServerRecord> {
  return apiPost(`${API_BASE}/mcp-connections/registry`, body);
}

export function deleteMCPServer(id: number): Promise<void> {
  return apiDelete(`${API_BASE}/mcp-connections/registry/${id}`);
}

export function discoverMCPServerTools(id: number): Promise<unknown> {
  return apiPost(`${API_BASE}/mcp-connections/registry/${id}/discover`);
}

export function pingMCPServerHealth(id: number): Promise<unknown> {
  return apiPost(`${API_BASE}/mcp-connections/registry/${id}/health`);
}

// ─── Connector OAuth status ───────────────────────────────────────────────────

export type ConnectorStatus = { connected: boolean };

export function getConnectorStatus(statusUrl: string): Promise<ConnectorStatus> {
  return apiGet(statusUrl);
}
