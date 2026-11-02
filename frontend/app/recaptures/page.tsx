"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RecaptureChart } from "@/components/charts";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ExperimentResult } from "@/lib/types";

export default function RecapturesPage() {
  const { token } = useAuth();
  const [experimentId, setExperimentId] = useState("");
  const [condition, setCondition] = useState("same_condition");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const experiments = useQuery({
    queryKey: ["experiments", token],
    enabled: Boolean(token),
    queryFn: () => api<{ experiments: { id: string; created_at: string; status: string }[] }>("/v1/experiments", token),
  });
  const detail = useQuery({
    queryKey: ["experiment", experimentId, token],
    enabled: Boolean(token && experimentId),
    queryFn: () => api<ExperimentResult>(`/v1/experiments/${experimentId}`, token),
  });
  const add = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.set("file", file);
      body.set("condition", condition);
      body.set("note", note);
      return api(`/v1/experiments/${experimentId}/recaptures`, token, { method: "POST", body });
    },
    onSuccess: () => {
      setMessage("Recapture queued as a new live task.");
      detail.refetch();
    },
    onError: (reason) => setMessage(reason instanceof ApiError ? `${reason.message} ${reason.remediation}` : "Could not add the recapture."),
  });
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">04 / Compare recaptures</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">Genuine recaptures</h1>
      <p className="mt-2 max-w-2xl text-mute">Add a new photograph taken in the same conditions or in changed conditions. It is a separate live YouCam task, shown beside the synthetic deltas for that session only.</p>
      {!token && <p className="mt-4">Sign in on the Capture page.</p>}
      {token && (
        <div className="mt-6 grid gap-3 sm:max-w-xl">
          <label>
            Audit
            <select className="mt-1 w-full rounded-2xl border border-line px-3 py-2" value={experimentId} onChange={(event) => setExperimentId(event.target.value)}>
              <option value="">Choose</option>
              {experiments.data?.experiments.map((item) => (
                <option key={item.id} value={item.id}>{item.status} · {new Date(item.created_at).toLocaleString()}</option>
              ))}
            </select>
          </label>
          <label>
            Condition
            <select className="mt-1 w-full rounded-2xl border border-line px-3 py-2" value={condition} onChange={(event) => setCondition(event.target.value)}>
              <option value="same_condition">Same condition</option>
              <option value="changed_condition">Changed condition</option>
            </select>
          </label>
          <label>
            Note
            <input className="mt-1 w-full rounded-2xl border border-line px-3 py-2" value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
          <label className="rounded-full bg-pink px-4 py-2 text-center text-sm font-semibold text-white">
            Add recapture
            <input className="sr-only" type="file" accept="image/*" onChange={(event) => event.target.files?.[0] && experimentId && add.mutate(event.target.files[0])} />
          </label>
          {message && <p className="text-sm">{message}</p>}
        </div>
      )}
      {detail.data && (
        <div className="mt-8">
          <RecaptureChart result={detail.data} />
        </div>
      )}
    </div>
  );
}
