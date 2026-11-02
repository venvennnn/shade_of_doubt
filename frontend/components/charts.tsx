"use client";

import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ExperimentResult, ScoreCell } from "@/lib/types";
import { variantLabel } from "@/lib/types";

type SelectCell = (cell: ScoreCell) => void;

function formatSigned(value: number | null) {
  if (value === null || Number.isNaN(value)) return "Unavailable";
  const rounded = Math.round(value * 100) / 100;
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function tone(value: number | null) {
  if (value === null) return "hatched text-mute";
  if (value > 0) return "bg-blush text-pink";
  if (value < 0) return "bg-slate-100 text-slate-700";
  return "bg-wash text-ink";
}

export function Heatmap({ result, onSelect }: { result: ExperimentResult; onSelect: SelectCell }) {
  const variants = result.variants.filter((item) => item.role === "variant");
  const concerns = result.config.concerns;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-left text-sm">
        <caption className="sr-only">Signed raw-score deltas by concern and transformation. Unavailable cells are labelled.</caption>
        <thead>
          <tr>
            <th className="p-2 font-medium text-mute">Concern</th>
            {variants.map((variant) => (
              <th key={variant.id} className="p-2 font-medium">
                {variantLabel(variant.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {concerns.map((concern) => (
            <tr key={concern}>
              <th className="p-2 font-medium capitalize">{concern.replaceAll("_", " ")}</th>
              {variants.map((variant) => {
                const cell = result.sensitivity.cells.find((item) => item.concern === concern && item.variant_id === variant.id);
                const value = cell?.delta ?? null;
                return (
                  <td key={variant.id}>
                    <button
                      type="button"
                      className={`w-full rounded-xl px-2 py-3 text-center ${tone(value)}`}
                      onClick={() => cell && onSelect(cell)}
                    >
                      <span className="block text-xs uppercase tracking-wide">delta</span>
                      {formatSigned(value)}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Curves({ result, onSelect }: { result: ExperimentResult; onSelect: SelectCell }) {
  const concerns = result.config.concerns;
  return (
    <div className="space-y-8">
      {concerns.map((concern) => {
        const exposure = series(result, concern, ["exposure_low", "baseline", "exposure_high"], exposureX);
        const colour = series(result, concern, ["colour_cool", "baseline", "colour_warm"], colourX);
        return (
          <div key={concern}>
            <h3 className="mb-2 capitalize font-semibold">{concern.replaceAll("_", " ")}</h3>
            <div className="grid gap-4 md:grid-cols-2">
              <Curve title="Exposure multiplier" data={exposure} unit="raw score" />
              <Curve title="Red channel gain" data={colour} unit="raw score" />
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {result.sensitivity.cells
                .filter((cell) => cell.concern === concern)
                .map((cell) => (
                  <button key={cell.variant_id} className="rounded-full border border-line px-3 py-1 text-xs" type="button" onClick={() => onSelect(cell)}>
                    {variantLabel(cell.variant_key)} {formatSigned(cell.delta)}
                  </button>
                ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function exposureX(key: string) {
  if (key === "exposure_low") return 0.9;
  if (key === "exposure_high") return 1.1;
  return 1;
}

function colourX(key: string) {
  if (key === "colour_cool") return 0.97;
  if (key === "colour_warm") return 1.03;
  return 1;
}

function series(result: ExperimentResult, concern: string, keys: string[], xOf: (key: string) => number) {
  return keys
    .map((key) => {
      const variant = result.variants.find((item) => item.key === key);
      const raw = variant?.scores?.[concern]?.raw_score;
      if (!variant || raw === null || raw === undefined) return null;
      return { x: xOf(key), y: raw, name: variantLabel(key) };
    })
    .filter((item): item is { x: number; y: number; name: string } => item !== null);
}

function Curve({ title, data, unit }: { title: string; data: { x: number; y: number; name: string }[]; unit: string }) {
  return (
    <figure className="rounded-2xl border border-line p-3">
      <figcaption className="mb-2 text-sm text-mute">
        {title}. Straight segments join tested points only. {unit}.
      </figcaption>
      {data.length === 0 ? (
        <p className="text-sm">Unavailable. No raw scores for these settings.</p>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tick={{ fill: "#17171f", fontSize: 12 }} />
              <YAxis tick={{ fill: "#17171f", fontSize: 12 }} domain={["auto", "auto"]} />
              <Tooltip />
              <Line type="linear" dataKey="y" stroke="#ff2f86" strokeWidth={2} dot={{ r: 4, fill: "#17171f" }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

export function Spread({ result, onSelect }: { result: ExperimentResult; onSelect: SelectCell }) {
  return (
    <div className="space-y-5">
      {result.config.concerns.map((concern) => {
        const baseline = result.variants.find((item) => item.role === "baseline")?.scores?.[concern]?.raw_score ?? null;
        const points = result.variants
          .map((variant) => ({ variant, raw: variant.scores?.[concern]?.raw_score ?? null }))
          .filter((item) => item.raw !== null) as { variant: ExperimentResult["variants"][number]; raw: number }[];
        const values = points.map((item) => item.raw);
        const min = values.length ? Math.min(...values) - 1 : 0;
        const max = values.length ? Math.max(...values) + 1 : 1;
        const span = Math.max(max - min, 1);
        return (
          <div key={concern}>
            <div className="mb-1 flex justify-between text-sm">
              <span className="capitalize font-medium">{concern.replaceAll("_", " ")}</span>
              <span className="text-mute">raw score</span>
            </div>
            <div className="relative h-10 rounded-full bg-wash">
              {points.map((item) => {
                const left = ((item.raw - min) / span) * 100;
                const cell = result.sensitivity.cells.find((entry) => entry.concern === concern && entry.variant_id === item.variant.id);
                const baselineMark = item.variant.role === "baseline";
                return (
                  <button
                    key={item.variant.id}
                    type="button"
                    className={`absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white ${baselineMark ? "h-5 w-5 bg-ink" : "bg-pink"}`}
                    style={{ left: `${left}%` }}
                    aria-label={`${variantLabel(item.variant.key)} raw ${item.raw}`}
                    onClick={() => cell && onSelect(cell)}
                  />
                );
              })}
            </div>
            <p className="mt-1 text-xs text-mute">
              {baseline === null ? "Baseline raw score unavailable." : `Baseline marker is the dark dot at ${baseline}.`} Pink dots are variants. No density estimate is drawn.
            </p>
          </div>
        );
      })}
    </div>
  );
}

export function Transitions({ result, variantId }: { result: ExperimentResult; variantId: string | null }) {
  const baseline = result.ranking.baseline;
  const chosen = result.ranking.variants.find((item) => item.variant_id === variantId) || result.ranking.variants[0];
  if (!baseline?.eligible || !chosen) {
    return <p className="text-sm">No eligible product ranking was frozen for this audit. The recommendation summary stays insufficient evidence.</p>;
  }
  return (
    <div>
      <p className="mb-3 text-sm text-mute">
        {variantLabel(chosen.variant_key)}. {chosen.comparison.comparable ? (chosen.comparison.top_one_changed ? "Top suggestion changed." : "Top suggestion unchanged.") : chosen.comparison.reason}
        {chosen.comparison.top_k_overlap_count !== undefined ? ` Top-${chosen.comparison.top_k} overlap ${chosen.comparison.top_k_overlap_count}.` : ""}
        {baseline.margin !== null ? ` Baseline match margin ${baseline.margin.toFixed(2)}.` : " Baseline match margin unavailable."}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <RankColumn title="Baseline" rows={baseline.ordered} />
        <RankColumn title={variantLabel(chosen.variant_key)} rows={chosen.ranking.ordered} changed={chosen.comparison.top_one_changed} />
      </div>
      {chosen.comparison.displacements && (
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">Rank displacement from baseline to the selected variant</caption>
          <thead>
            <tr className="text-left text-mute">
              <th>Product</th>
              <th>Baseline rank</th>
              <th>Variant rank</th>
              <th>Displacement</th>
            </tr>
          </thead>
          <tbody>
            {chosen.comparison.displacements.map((row) => (
              <tr key={row.product_id} className="border-t border-line">
                <td className="py-1">{nameOf(result, row.product_id)}</td>
                <td>{row.baseline_rank ?? "—"}</td>
                <td>{row.variant_rank ?? "—"}</td>
                <td>{row.displacement === null ? "not in both lists" : formatSigned(row.displacement)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function nameOf(result: ExperimentResult, productId: string) {
  const lists = [result.ranking.baseline?.ordered || [], ...result.ranking.variants.map((item) => item.ranking.ordered)];
  for (const list of lists) {
    const found = list.find((item) => item.product_id === productId);
    if (found) return found.name;
  }
  return productId;
}

function RankColumn({ title, rows, changed }: { title: string; rows: { rank: number; name: string; match: number; score_tie: boolean; source_url: string }[]; changed?: boolean }) {
  return (
    <ol className={`rounded-2xl border p-4 ${changed ? "border-pink" : "border-line"}`}>
      <li className="mb-2 list-none font-semibold">{title}</li>
      {rows.slice(0, 5).map((row) => (
        <li key={row.rank} className="flex items-baseline justify-between gap-3 border-t border-line py-2 text-sm">
          <span>
            {row.rank}. {row.name} {row.score_tie ? <em className="text-mute">tie on match score</em> : null}
          </span>
          <a className="text-pink" href={row.source_url}>
            source
          </a>
        </li>
      ))}
    </ol>
  );
}

export function RawUi({ result, onSelect }: { result: ExperimentResult; onSelect: SelectCell }) {
  const concern = result.config.concerns[0];
  const rows = result.sensitivity.cells.filter((cell) => cell.concern === concern);
  const raw = rows.map((cell) => ({ name: variantLabel(cell.variant_key), delta: cell.delta ?? 0, missing: cell.delta === null }));
  const ui = rows.map((cell) => ({ name: variantLabel(cell.variant_key), delta: cell.ui_delta ?? 0, missing: cell.ui_delta === null }));
  return (
    <div>
      <p className="mb-3 text-sm text-mute">
        Showing {concern.replaceAll("_", " ")}. Raw and UI deltas use separate charts because the provider adjusts UI scores for presentation. Missing values are listed under the charts and are not drawn as zero in the table.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <MiniBars title="Raw score delta" data={raw.filter((item) => !item.missing)} />
        <MiniBars title="UI score delta" data={ui.filter((item) => !item.missing)} />
      </div>
      <ul className="mt-3 space-y-1 text-sm">
        {rows.map((cell) => (
          <li key={cell.variant_id}>
            <button type="button" className="underline decoration-pink/40" onClick={() => onSelect(cell)}>
              {variantLabel(cell.variant_key)}
            </button>
            : raw {formatSigned(cell.delta)}
            {cell.unavailable_reason ? ` (${cell.unavailable_reason})` : ""}; UI {formatSigned(cell.ui_delta)}
            {cell.ui_unavailable_reason ? ` (${cell.ui_unavailable_reason})` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MiniBars({ title, data }: { title: string; data: { name: string; delta: number }[] }) {
  return (
    <figure className="rounded-2xl border border-line p-3">
      <figcaption className="mb-2 text-sm">{title}</figcaption>
      {data.length === 0 ? (
        <p className="text-sm">Unavailable.</p>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <XAxis dataKey="name" tick={{ fill: "#17171f", fontSize: 11 }} interval={0} />
              <YAxis tick={{ fill: "#17171f", fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="delta" fill="#ff2f86" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

export function RecaptureChart({ result }: { result: ExperimentResult }) {
  if (result.recaptures.length === 0) {
    return <p className="text-sm">No genuine recaptures have been added. Synthetic deltas are not treated as a pooled capture study.</p>;
  }
  return (
    <div className="space-y-6">
      {result.recaptures.map((session) => (
        <section key={session.id} className="rounded-2xl border border-line p-4">
          <h3 className="font-semibold">
            {session.condition.replaceAll("_", " ")} · {session.status}
          </h3>
          <p className="text-sm text-mute">{session.note || "No note."} Provider task {session.provider_task_id || "not assigned"}.</p>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-mute">
                <th>Concern</th>
                <th>Recapture delta</th>
                <th>Largest absolute synthetic delta</th>
              </tr>
            </thead>
            <tbody>
              {session.concerns.map((row) => (
                <tr key={row.concern} className="border-t border-line">
                  <td className="py-1 capitalize">{row.concern.replaceAll("_", " ")}</td>
                  <td>{row.recapture_delta === null ? row.unavailable_reason || "Unavailable" : formatSigned(row.recapture_delta)}</td>
                  <td>{row.synthetic_max_abs_delta === null ? "Unavailable" : row.synthetic_max_abs_delta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      <p className="text-xs text-mute">Sessions stay separate. This installation does not fit a threshold or claim that synthetic sensitivity predicts capture instability.</p>
    </div>
  );
}
