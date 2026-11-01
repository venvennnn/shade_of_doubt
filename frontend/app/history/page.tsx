"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function HistoryPage() {
  const { token } = useAuth();
  const experiments = useQuery({
    queryKey: ["experiments", token],
    enabled: Boolean(token),
    queryFn: () => api<{ experiments: { id: string; status: string; created_at: string; summary: { label?: string; statement?: string } | null }[] }>("/v1/experiments", token),
  });
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">04 / History</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">Past audits</h1>
      {!token && <p className="mt-3">Sign in to see history for this account.</p>}
      <ul className="mt-6 space-y-3">
        {experiments.data?.experiments.map((item) => (
          <li key={item.id} className="rounded-[24px] border border-line p-4">
            <p className="text-sm text-mute">{new Date(item.created_at).toLocaleString()}</p>
            <p className="font-semibold">{item.summary?.label || item.status}</p>
            <p className="text-sm">{item.summary?.statement || "No concluded statement."}</p>
            <div className="mt-2 flex gap-3 text-sm">
              <Link className="text-pink" href={`/audit/${item.id}`}>Open</Link>
              <button
                className="text-pink"
                type="button"
                onClick={async () => {
                  const report = await api(`/v1/experiments/${item.id}/report`, token);
                  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement("a");
                  anchor.href = url;
                  anchor.download = `shade-of-doubt-${item.id}.json`;
                  anchor.click();
                  URL.revokeObjectURL(url);
                }}
              >
                Report JSON
              </button>
              <DeleteButton id={item.id} token={token || ""} />
            </div>
          </li>
        ))}
      </ul>
      {token && (
        <button
          className="mt-6 text-sm text-mute underline"
          type="button"
          onClick={async () => {
            if (confirm("Delete this account’s photographs, audits, and catalogue? Quota ledger rows are removed with the account.")) {
              await api("/v1/account", token, { method: "DELETE" });
              window.location.href = "/capture";
            }
          }}
        >
          Delete account data
        </button>
      )}
    </div>
  );
}

function DeleteButton({ id, token }: { id: string; token: string }) {
  return (
    <button
      className="text-mute"
      type="button"
      onClick={async () => {
        if (!confirm("Delete this audit, its photographs, and derived scores?")) return;
        await api(`/v1/experiments/${id}`, token, { method: "DELETE" });
        window.location.reload();
      }}
    >
      Delete
    </button>
  );
}
