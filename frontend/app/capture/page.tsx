"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AssetRecord, Plan, Product, RuntimeInfo } from "@/lib/types";

const FACTORS = [
  ["exposure", "Exposure 0.9 and 1.1"],
  ["colour_balance", "Warm and cool channel gains"],
  ["framing", "Left and right 2% framing"],
] as const;

export default function CapturePage() {
  const auth = useAuth();
  const router = useRouter();
  const runtime = useQuery({ queryKey: ["runtime"], queryFn: () => api<RuntimeInfo>("/v1/runtime", null) });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tokenDraft, setTokenDraft] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [external, setExternal] = useState(false);
  const [retention, setRetention] = useState(false);
  const [asset, setAsset] = useState<AssetRecord | null>(null);
  const [concerns, setConcerns] = useState<string[]>([]);
  const [factors, setFactors] = useState<string[]>(FACTORS.map((item) => item[0]));
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [cameraOn, setCameraOn] = useState(false);

  useEffect(() => {
    if (runtime.data && concerns.length === 0) setConcerns(runtime.data.concerns);
  }, [runtime.data, concerns.length]);

  const products = useQuery({
    queryKey: ["products", auth.token],
    enabled: Boolean(auth.token),
    queryFn: () => api<{ products: Product[] }>("/v1/products", auth.token),
  });
  const guided = useQuery({
    queryKey: ["guided", auth.token],
    enabled: Boolean(auth.token),
    queryFn: () => api<{ guided_assets: { id: string; title: string; rights_statement: string; consent_statement: string }[] }>("/v1/guided-assets", auth.token),
  });

  async function consent() {
    setError("");
    await api("/v1/consents", auth.token, { method: "POST", body: JSON.stringify({ external_processing: external, retention_acknowledged: retention }) });
  }

  async function upload(file: File) {
    setError("");
    const body = new FormData();
    body.set("file", file);
    try {
      const saved = await api<AssetRecord>("/v1/assets", auth.token, { method: "POST", body });
      setAsset(saved);
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  async function captureFrame(video: HTMLVideoElement) {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (blob) await upload(new File([blob], "capture.png", { type: "image/png" }));
  }

  const planMutation = useMutation({
    mutationFn: () =>
      api<Plan>("/v1/experiments/plan", auth.token, {
        method: "POST",
        body: JSON.stringify({ concerns, factors, product_ids: selectedProducts }),
      }),
    onSuccess: setPlan,
    onError: (reason) => setError(messageOf(reason)),
  });

  const runMutation = useMutation({
    mutationFn: (guidedId?: string) =>
      api<{ experiment_id: string }>("/v1/experiments", auth.token, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          asset_id: guidedId ? undefined : asset?.id,
          guided_asset_id: guidedId,
          concerns,
          factors,
          product_ids: selectedProducts,
        }),
      }),
    onSuccess: (result) => router.push(`/audit/${result.experiment_id}`),
    onError: (reason) => setError(messageOf(reason)),
  });

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">01 / Capture</p>
      <h1 className="mt-2 max-w-3xl text-4xl font-semibold tracking-tight">Start with a real photograph and a stated consent.</h1>
      <p className="mt-2 max-w-2xl text-mute">The audit submits the unmodified baseline first. If YouCam rejects it, variant tasks are not sent.</p>

      <section className="mt-8 rounded-[28px] border border-line p-5">
        <h2 className="text-xl font-semibold">Sign in</h2>
        {auth.configured ? (
          <form
            className="mt-3 grid gap-3 sm:max-w-md"
            onSubmit={async (event) => {
              event.preventDefault();
              setAuthMessage("");
              try {
                await auth.signIn(email, password);
              } catch (reason) {
                setAuthMessage(messageOf(reason));
              }
            }}
          >
            <label>Email<input className="mt-1 w-full rounded-2xl border border-line px-3 py-2" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
            <label>Password<input className="mt-1 w-full rounded-2xl border border-line px-3 py-2" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
            <div className="flex gap-2">
              <button className="rounded-full bg-ink px-4 py-2 text-sm text-white" type="submit">Sign in</button>
              <button
                className="rounded-full border border-line px-4 py-2 text-sm"
                type="button"
                onClick={async () => {
                  try {
                    setAuthMessage(await auth.signUp(email, password));
                  } catch (reason) {
                    setAuthMessage(messageOf(reason));
                  }
                }}
              >
                Create account
              </button>
            </div>
          </form>
        ) : (
          <div className="mt-3 text-sm">
            <p>Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> to use Supabase sign-in.</p>
            <form
              className="mt-3"
              onSubmit={(event) => {
                event.preventDefault();
                auth.useToken(tokenDraft.trim());
              }}
            >
              <label>
                Local access token
                <input className="mt-1 w-full rounded-2xl border border-line px-3 py-2" value={tokenDraft} onChange={(event) => setTokenDraft(event.target.value)} />
              </label>
              <button className="mt-2 rounded-full bg-ink px-4 py-2 text-sm text-white" type="submit">Use token</button>
            </form>
          </div>
        )}
        {authMessage && <p className="mt-2 text-sm">{authMessage}</p>}
        {auth.token && <p className="mt-2 text-sm text-mute">Signed in{auth.email ? ` as ${auth.email}` : ""}.</p>}
      </section>

      {runtime.isError && <p className="mt-4 text-sm" role="alert">The API at NEXT_PUBLIC_API_URL could not be reached. Start the API and check the URL baked into this frontend build.</p>}
      {runtime.data && (
        <section className="mt-5 rounded-[28px] bg-wash p-5 text-sm">
          <p>{runtime.data.youcam_configured ? "YouCam key is configured." : "YouCam key is missing. Live tasks will be refused."}</p>
          <p>{runtime.data.pricing_configured ? `Configured estimate: ${runtime.data.unit_cost_per_task} units per task.` : runtime.data.pricing_error?.message}</p>
          {!runtime.data.pricing_configured && <p>{runtime.data.pricing_error?.remediation}</p>}
        </section>
      )}

      <section className="mt-5 rounded-[28px] border border-line p-5">
        <h2 className="text-xl font-semibold">Consent</h2>
        <p className="mt-2 text-sm leading-6">{runtime.data?.consent_text || "Loading the consent statement."}</p>
        <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} /> I agree to external YouCam processing.</label>
        <label className="mt-2 flex gap-2 text-sm"><input type="checkbox" checked={retention} onChange={(event) => setRetention(event.target.checked)} /> I understand the stated retention, including provider copies this app cannot delete.</label>
        <button className="mt-3 rounded-full bg-ink px-4 py-2 text-sm text-white" type="button" onClick={() => consent().catch((reason) => setError(messageOf(reason)))}>Save consent</button>
      </section>

      <section className="mt-5 rounded-[28px] border border-line p-5">
        <h2 className="text-xl font-semibold">Photograph</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <label className="rounded-full bg-pink px-4 py-2 text-sm font-semibold text-white">
            Upload
            <input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
          </label>
          <button className="rounded-full border border-line px-4 py-2 text-sm" type="button" onClick={() => setCameraOn((value) => !value)}>Use camera</button>
        </div>
        {cameraOn && <Camera onCapture={captureFrame} />}
        {guided.data && guided.data.guided_assets.length > 0 && (
          <ul className="mt-4 space-y-2 text-sm">
            {guided.data.guided_assets.map((item) => (
              <li key={item.id} className="rounded-2xl bg-wash p-3">
                <p className="font-medium">{item.title}</p>
                <p>{item.rights_statement}</p>
                <p>{item.consent_statement}</p>
                <button className="mt-2 text-pink" type="button" onClick={() => runMutation.mutate(item.id)}>Run a fresh guided audit</button>
              </li>
            ))}
          </ul>
        )}
        {guided.data && guided.data.guided_assets.length === 0 && <p className="mt-3 text-sm text-mute">No rights-cleared guided photograph is published. Upload is required.</p>}
        {asset && (
          <ul className="mt-4 space-y-2 text-sm">
            <li>{asset.width}×{asset.height} · {asset.sha256.slice(0, 12)}</li>
            {asset.validation.checks.map((check) => (
              <li key={check.name}>
                <span className="font-semibold capitalize">{check.status}</span> · {check.name}: {check.detail}
                <span className="block text-mute">{check.heuristic}</span>
              </li>
            ))}
            <li className="text-mute">{asset.validation.disclaimer}</li>
          </ul>
        )}
      </section>

      <section className="mt-5 rounded-[28px] border border-line p-5">
        <h2 className="text-xl font-semibold">Concerns, factors, and products</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {(runtime.data?.concerns || concerns).map((concern) => (
            <label key={concern} className="rounded-full border border-line px-3 py-1 text-sm capitalize">
              <input
                className="mr-2"
                type="checkbox"
                checked={concerns.includes(concern)}
                onChange={(event) => setConcerns((current) => event.target.checked ? [...current, concern] : current.filter((item) => item !== concern))}
              />
              {concern.replaceAll("_", " ")}
            </label>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {FACTORS.map(([key, label]) => (
            <label key={key} className="rounded-full border border-line px-3 py-1 text-sm">
              <input
                className="mr-2"
                type="checkbox"
                checked={factors.includes(key)}
                onChange={(event) => setFactors((current) => event.target.checked ? [...current, key] : current.filter((item) => item !== key))}
              />
              {label}
            </label>
          ))}
        </div>
        <p className="mt-4 text-sm">
          Optional real shortlist. <Link className="text-pink" href="/catalogue">Add a confirmed product</Link> from a source you checked. Empty means score-only, and the product decision is insufficient evidence.
        </p>
        <ul className="mt-2 space-y-1 text-sm">
          {(products.data?.products || []).filter((item) => item.confirmed).map((product) => (
            <li key={product.id}>
              <label>
                <input
                  className="mr-2"
                  type="checkbox"
                  checked={selectedProducts.includes(product.id)}
                  onChange={(event) => setSelectedProducts((current) => event.target.checked ? [...current, product.id] : current.filter((item) => item !== product.id))}
                />
                {product.name} · {product.price || "no price"} {product.currency || ""}
              </label>
            </li>
          ))}
        </ul>
        <button className="mt-4 rounded-full border border-line px-4 py-2 text-sm" type="button" onClick={() => planMutation.mutate()}>Show planned tasks and units</button>
        {plan && (
          <div className="mt-4 text-sm">
            <p>{plan.task_count} live tasks · estimated {plan.estimated_units} units at {plan.unit_cost_per_task} each. {plan.fresh_call}</p>
            <p className="text-mute">{plan.charge_note}</p>
            <ul className="mt-2 list-disc pl-5">
              {plan.tasks.map((task) => (
                <li key={task.key}>{task.role} · {task.key}</li>
              ))}
            </ul>
            <button className="mt-3 rounded-full bg-pink px-4 py-2 font-semibold text-white" type="button" onClick={() => runMutation.mutate(undefined)} disabled={!asset || runMutation.isPending}>
              {runMutation.isPending ? "Submitting" : "Run live audit"}
            </button>
          </div>
        )}
      </section>
      {error && <p className="mt-4 rounded-2xl bg-blush p-4 text-sm" role="alert">{error}</p>}
    </div>
  );
}

function Camera({ onCapture }: { onCapture: (video: HTMLVideoElement) => void }) {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (!video) return;
    let stream: MediaStream | null = null;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false }).then((next) => {
      stream = next;
      video.srcObject = next;
      video.play();
    }).catch(() => undefined);
    return () => stream?.getTracks().forEach((track) => track.stop());
  }, [video]);
  return (
    <div className="mt-3">
      <video ref={setVideo} className="max-h-80 rounded-2xl bg-ink" muted playsInline />
      <button className="mt-2 rounded-full bg-ink px-4 py-2 text-sm text-white" type="button" onClick={() => video && onCapture(video)}>Take photograph</button>
    </div>
  );
}

function messageOf(reason: unknown) {
  if (reason instanceof ApiError) return `${reason.message} ${reason.remediation}`.trim();
  if (reason instanceof Error) return reason.message;
  return "Something went wrong.";
}
