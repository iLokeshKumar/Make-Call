import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getMCPServers,
  createMCPServer,
  deleteMCPServer,
  discoverMCPServerTools,
  pingMCPServerHealth,
  type MCPServerCreate,
} from "@/lib/api";

export function useMCPServers() {
  return useQuery({
    queryKey: ["mcp-servers"],
    queryFn: getMCPServers,
    staleTime: 60_000,
  });
}

export function useCreateMCPServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: MCPServerCreate) => createMCPServer(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });
}

export function useDeleteMCPServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteMCPServer(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });
}

export function useDiscoverMCPTools() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => discoverMCPServerTools(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });
}

export function usePingMCPHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => pingMCPServerHealth(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });
}
