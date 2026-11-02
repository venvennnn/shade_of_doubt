"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Workspace } from "@/components/workspace";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ExperimentResult } from "@/lib/types";

export default function AuditPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const result = useQuery({
    queryKey: ["experiment", params.id, token],
    enabled: Boolean(token && params.id),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 3000 : false),
    queryFn: () => api<ExperimentResult>(`/v1/experiments/${params.id}`, token),
  });
  if (!token) return <p>Preparing this browser.</p>;
  if (result.isLoading) return <p>Loading the audit.</p>;
  if (result.error) return <p role="alert">{(result.error as Error).message}</p>;
  if (!result.data) return null;
  return <Workspace result={result.data} />;
}
