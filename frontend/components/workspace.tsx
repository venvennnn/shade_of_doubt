"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Curves, Heatmap, RawUi, RecaptureChart, Spread, Transitions } from "./charts";
import { Photo } from "./photos";
import type { ExperimentResult, ScoreCell, VariantView } from "@/lib/types";
import { variantLabel } from "@/lib/types";

const SUMMARY_TEXT: Record<string, string> = {
  recommendation_changed: "Recommendation changed",
  stable_under_tested_transformations: "Stable under tested transformations",
  insufficient_evidence: "Insufficient evidence",
  in_progress: "In progress",
};

export function Workspace({ result }: { result: ExperimentResult }) {
  const variants = result.variants.filter((item) => item.role === "variant");
  const baseline = result.variants.find((item) => item.role === "baseline") || null;
  const [selectedId, setSelectedId] = useState(variants[0]?.id || baseline?.id || "");
  const [concern, setConcern] = useState(result.config.concerns[0] || "texture");
  const [cell, setCell] = useState<ScoreCell | null>(null);
  const selected = result.variants.find((item) => item.id === selectedId) || variants[0] || baseline;
  const comparison = result.ranking.variants.find((item) => item.variant_id === selected?.id);

  function cycle(step: number) {
    const ids = result.variants.map((item) => item.id);
    const index = Math.max(0, ids.indexOf(selected?.id || ""));
    setSelectedId(ids[(index + step + ids.length) % ids.length]);
  }

  const cells = result.sensitivity.cells.filter((item) => item.concern === concern);
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">03 / The audit</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="max-w-3xl text-4xl font-semibold tracking-tight">Small photo changes. Different shopping advice?</h1>
          <p className="mt-2 max-w-2xl text-mute">Test whether controlled changes to this photograph move model appearance scores and the frozen product ranking.</p>
        </div>
        <Link href="/capture" className="rounded-full bg-pink px-4 py-2 text-sm font-semibold text-white">
          Retake
        </Link>
      </div>

      <section className="mt-6 grid gap-5 lg:grid-cols-[1.4fr_0.8fr]" aria-label="Comparison">
        <div>
          <div className="grid gap-3 md:grid-cols-2">
            <figure className="overflow-hidden rounded-[28px] bg-wash">
              <div className="relative aspect-[4/5]">
                <Photo assetId={baseline?.asset_id} alt="Unmodified normalised baseline" />
                <figcaption className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold">Original</figcaption>
              </div>
            </figure>
            <figure className="overflow-hidden rounded-[28px] bg-wash">
              <div className="relative aspect-[4/5]">
                <Photo assetId={selected?.asset_id} alt={selected ? variantLabel(selected.key) : "Variant"} />
                <figcaption className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1 text-xs font-semibold">
                  {selected ? variantLabel(selected.key) : "Variant"}
                </figcaption>
              </div>
            </figure>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex gap-2 overflow-x-auto py-1" role="listbox" aria-label="Variants" onKeyDown={(event) => {
              if (event.key === "ArrowRight") cycle(1);
              if (event.key === "ArrowLeft") cycle(-1);
            }}>
              {result.variants.map((variant) => (
                <button
                  key={variant.id}
                  type="button"
                  role="option"
                  aria-selected={variant.id === selected?.id}
                  className={`w-20 shrink-0 ${variant.id === selected?.id ? "rounded-2xl ring-2 ring-pink" : ""}`}
                  onClick={() => setSelectedId(variant.id)}
                >
                  <span className="block overflow-hidden rounded-2xl">
                    <span className="block aspect-square">
                      <Photo assetId={variant.asset_id} alt="" />
                    </span>
                  </span>
                  <span className={`mt-1 block text-center text-xs ${variant.id === selected?.id ? "font-semibold text-pink" : "text-mute"}`}>
                    {variantLabel(variant.key)}
                  </span>
                </button>
              ))}
            </div>
            <button type="button" className="h-10 w-10 shrink-0 rounded-full border border-line" aria-label="Next variant" onClick={() => cycle(1)}>
              ›
            </button>
          </div>
          {selected && <Parameters variant={selected} />}
        </div>
        <aside className="space-y-4">
          <Progress result={result} />
          <div className="rounded-[28px] border border-line p-4 shadow-card">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">This variant’s effect</h2>
                <p className="text-xs text-mute">Raw score change versus the original. Higher raw means healthier-looking in the provider documentation, not a larger physical trait.</p>
              </div>
              <label className="text-xs text-mute">
                Concern
                <select className="mt-1 block rounded-full border border-line px-2 py-1 text-ink" value={concern} onChange={(event) => setConcern(event.target.value)}>
                  {result.config.concerns.map((item) => (
                    <option key={item} value={item}>{item.replaceAll("_", " ")}</option>
                  ))}
                </select>
              </label>
            </div>
            <ul className="mt-4 space-y-3">
              {cells.map((item) => (
                <li key={item.variant_id}>
                  <button type="button" className="w-full text-left" onClick={() => setCell(item)}>
                    <span className="flex items-center justify-between text-sm">
                      <span>{variantLabel(item.variant_key)}</span>
                      <span className="font-semibold">{item.delta === null ? "Unavailable" : signed(item.delta)}</span>
                    </span>
                    <span className="mt-1 block h-2 rounded-full bg-wash">
                      {item.delta !== null && (
                        <span
                          className={`block h-2 rounded-full ${item.delta >= 0 ? "bg-pink" : "bg-slate-500"}`}
                          style={{ width: `${Math.min(100, Math.abs(item.delta) * 8)}%`, marginLeft: item.delta < 0 ? "auto" : undefined }}
                        />
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <Recommendation result={result} selected={selected || null} changed={Boolean(comparison?.comparison.top_one_changed)} />
        </aside>
      </section>

      <section className="mt-8 rounded-[28px] border border-line p-5">
        <h2 className="font-semibold">Across the tested variants</h2>
        <p className="text-sm text-mute">Each mark is a persisted raw-score delta for {concern.replaceAll("_", " ")}. Invalid variants are omitted rather than treated as zero.</p>
        <Spread result={{ ...result, config: { ...result.config, concerns: [concern] } }} onSelect={setCell} />
      </section>

      <section className="mt-8" aria-label="Six result graphs">
        <Tabs.Root defaultValue="heatmap">
          <Tabs.List className="flex flex-wrap gap-2" aria-label="Graphs">
            {[
              ["heatmap", "Sensitivity"],
              ["curves", "Paired curves"],
              ["spread", "Score spread"],
              ["decisions", "Recommendation transitions"],
              ["raw", "Raw versus UI"],
              ["recapture", "Recaptures"],
            ].map(([value, label]) => (
              <Tabs.Trigger key={value} value={value} className="rounded-full border border-line px-3 py-1.5 text-sm data-[state=active]:border-pink data-[state=active]:bg-blush data-[state=active]:text-pink">
                {label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="heatmap" className="mt-4"><Heatmap result={result} onSelect={setCell} /></Tabs.Content>
          <Tabs.Content value="curves" className="mt-4"><Curves result={result} onSelect={setCell} /></Tabs.Content>
          <Tabs.Content value="spread" className="mt-4"><Spread result={result} onSelect={setCell} /></Tabs.Content>
          <Tabs.Content value="decisions" className="mt-4"><Transitions result={result} variantId={selected?.id || null} /></Tabs.Content>
          <Tabs.Content value="raw" className="mt-4"><RawUi result={result} onSelect={setCell} /></Tabs.Content>
          <Tabs.Content value="recapture" className="mt-4"><RecaptureChart result={result} /></Tabs.Content>
        </Tabs.Root>
      </section>

      <CellDialog result={result} cell={cell} onClose={() => setCell(null)} />
      <Limitations result={result} />
    </div>
  );
}

function signed(value: number) {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function Parameters({ variant }: { variant: VariantView }) {
  return (
    <div className="mt-3 rounded-2xl bg-wash p-3 text-sm">
      <p className="font-medium">Applied parameters · {variant.status.replaceAll("_", " ")}</p>
      <p className="text-mute">{variant.pipeline_version} · {variant.colour_conversion} · {variant.resize_method} · {variant.encode_method}</p>
      <p className="mt-1 break-words">{JSON.stringify(variant.params)}</p>
      {variant.rejection_reason && <p className="mt-1 text-pink">{variant.rejection_reason}</p>}
    </div>
  );
}

function Progress({ result }: { result: ExperimentResult }) {
  const counts = result.counts;
  const label = SUMMARY_TEXT[result.summary.label] || result.summary.label;
  return (
    <div className="rounded-[28px] border border-line p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-pink">{label}</p>
      <p className="mt-1 text-sm">{result.summary.statement}</p>
      <p className="mt-2 text-sm text-mute">{result.stage_label}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <Count label="Submitted" value={counts.submitted} />
        <Count label="Accepted" value={counts.accepted} />
        <Count label="Rejected locally" value={counts.rejected_local} />
        <Count label="Provider failed" value={counts.provider_failed} />
      </dl>
      {result.error_message && <p className="mt-2 text-sm">{result.error_message}</p>}
    </div>
  );
}

function Count({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-2xl bg-wash px-3 py-2">
      <dt className="text-xs text-mute">{label}</dt>
      <dd className="font-semibold">{value ?? 0}</dd>
    </div>
  );
}

function Recommendation({ result, selected, changed }: { result: ExperimentResult; selected: VariantView | null; changed: boolean }) {
  const baselineTop = result.ranking.baseline?.ordered?.[0];
  const variantRank = result.ranking.variants.find((item) => item.variant_id === selected?.id);
  const variantTop = variantRank?.ranking.ordered?.[0];
  return (
    <div className="rounded-[28px] border border-line p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">Shopping suggestion</h2>
        {changed && <span className="rounded-full bg-blush px-2 py-1 text-xs font-semibold text-pink">Recommendation changed</span>}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <ProductCard title="Original top suggestion" product={baselineTop} />
        <ProductCard title="Variant top suggestion" product={variantTop} />
      </div>
      <p className="mt-3 text-xs text-mute">These are suggestions from the frozen rule. They are not personalised safety or efficacy advice. {String(result.ranking.formula.expression || "")}</p>
    </div>
  );
}

function ProductCard({ title, product }: { title: string; product?: { name: string; source_url: string; price: string | null; currency: string | null; score_tie: boolean } }) {
  return (
    <div className="rounded-2xl bg-wash p-3 text-sm">
      <p className="text-xs text-mute">{title}</p>
      {product ? (
        <>
          <p className="mt-1 font-semibold">{product.name}</p>
          <p>{product.price ? `${product.price} ${product.currency || ""}` : "Price not recorded"}</p>
          {product.score_tie && <p>Tied on match score</p>}
          <a className="text-pink" href={product.source_url}>View source</a>
        </>
      ) : (
        <p className="mt-1">No eligible product.</p>
      )}
    </div>
  );
}

function CellDialog({ result, cell, onClose }: { result: ExperimentResult; cell: ScoreCell | null; onClose: () => void }) {
  const variant = useMemo(() => result.variants.find((item) => item.id === cell?.variant_id) || null, [result, cell]);
  const baseline = result.variants.find((item) => item.role === "baseline");
  return (
    <Dialog.Root open={Boolean(cell)} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 max-h-[90vh] w-[min(920px,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-[28px] bg-white p-5">
          <Dialog.Title className="text-xl font-semibold">
            {cell ? `${cell.concern.replaceAll("_", " ")} · ${variantLabel(cell.variant_key)}` : "Detail"}
          </Dialog.Title>
          <Dialog.Description className="text-sm text-mute">Persisted images, parameters, scores, rule, and provider provenance.</Dialog.Description>
          {cell && variant && (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <Photo assetId={baseline?.asset_id} alt="Baseline" />
              <Photo assetId={variant.asset_id} alt={variantLabel(variant.key)} />
              <dl className="space-y-1 text-sm md:col-span-2">
                <div>Raw baseline {cell.baseline_raw_score ?? "unavailable"} · variant {cell.raw_score ?? "unavailable"} · delta {cell.delta ?? cell.unavailable_reason}</div>
                <div>UI baseline {cell.baseline_ui_score ?? "unavailable"} · variant {cell.ui_score ?? "unavailable"} · delta {cell.ui_delta ?? cell.ui_unavailable_reason}</div>
                <div>Pipeline {variant.pipeline_version}; crop {variant.crop_bounds ? JSON.stringify(variant.crop_bounds) : "none"}; clipping {variant.clipping_fraction ?? "n/a"}</div>
                <div>SHA-256 {variant.sha256 || "none"}</div>
                <div>Provider task {variant.provider?.provider_task_id || "none"} · status {variant.provider?.status || variant.status} · polls {variant.provider?.poll_count ?? 0} · schema {variant.provider?.schema_version || "n/a"}</div>
                <div>Rule: {String(result.ranking.formula.expression || "")}. Tie-break: {JSON.stringify(result.ranking.formula.tie_break || [])}.</div>
              </dl>
            </div>
          )}
          <Dialog.Close className="mt-4 rounded-full bg-ink px-4 py-2 text-sm text-white">Close</Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Limitations({ result }: { result: ExperimentResult }) {
  return (
    <ul className="mt-8 list-disc space-y-1 pl-5 text-xs text-mute">
      {result.limitations.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
