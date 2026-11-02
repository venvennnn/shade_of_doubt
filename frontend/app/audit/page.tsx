"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AuditIndex() {
  const { token } = useAuth();
  const experiments = useQuery({
    queryKey: ["experiments", token],
    enabled: Boolean(token),
    queryFn: () => api<{ experiments: { id: string; status: string; stage: string; created_at: string; summary: { statement?: string } | null }[] }>("/v1/experiments", token),
  });
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">03 / The audit</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">Audits</h1>
      {!token && <p className="mt-3">Preparing this browser.</p>}
      {token && experiments.data?.experiments.length === 0 && <p className="mt-3">No audits yet. A chart is not shown until a live run returns scores.</p>}
      <ul className="mt-6 space-y-3">
        {experiments.data?.experiments.map((item) => (
          <li key={item.id}>
            <Link className="block rounded-[24px] border border-line p-4" href={`/audit/${item.id}`}>
              <span className="font-semibold">{item.status}</span>
              <span className="ml-2 text-sm text-mute">{item.stage}</span>
              <span className="mt-1 block text-sm">{item.summary?.statement || "No conclusion yet."}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
