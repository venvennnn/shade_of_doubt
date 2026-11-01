import type { ReactNode } from "react";

export default function MethodsPage() {
  return (
    <article className="max-w-3xl">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">05 / Methods</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">How an audit is defined</h1>
      <p className="mt-3 text-mute">
        Shade of Doubt asks whether a shopping suggestion depends on how a photograph was captured. It does not diagnose skin, prescribe treatment, certify safety, or measure product efficacy.
      </p>
      <Section title="Provider">
        Tasks use YouCam AI Skin Analysis v2.1: file registration, then <code>POST /s2s/v2.1/task/skin-analysis</code> with <code>src_file_id</code> and <code>format=json</code>, then <code>GET /s2s/v2.1/task/skin-analysis/{"{task_id}"}</code>. The default file path is the documented <code>/s2s/v2.0/file</code> flow and can be overridden. SD and HD actions are never mixed. <code>pf_camera_kit</code> is not sent. Polling defaults to 10 seconds and honours <code>Retry-After</code>. Signed webhooks are accepted only when a secret is configured.
      </Section>
      <Section title="Scores">
        Sensitivity uses <code>raw_score</code>. <code>ui_score</code> is stored and plotted separately. Perfect Corp describes a higher raw score as a healthier-looking result in its documentation, not as a physical measurement. A higher redness score is not treated as greater redness. Missing raw scores stay unavailable.
      </Section>
      <Section title="Transformations">
        The default experiment is one unmodified baseline plus six variants, one factor at a time. Exposure multipliers 0.9 and 1.1 run in linear RGB after the IEC 61966-2-1 sRGB transfer. Warm and cool variants use red/blue gains 1.03/0.97 and 0.97/1.03, green unchanged. They are channel-gain perturbations, not measured colour temperatures. Framing shifts the crop by 2% of image width with equal windows and Lanczos resize back to the master size. That is a digital framing change, not head rotation. Variants that clip too much or push the face outside the crop are rejected and are not replaced.
      </Section>
      <Section title="Decisions">
        Product ranking is a frozen explicit sum of priority-weighted severity. With the documented direction, severity is 100 minus the raw score. Ties break by match, then price within one currency, then product id. Any top-one change is “recommendation changed”. No change is “unchanged in n tested variants”. A missing baseline, coverage below the configured minimum, or no eligible products is “insufficient evidence”. The minimum is an engineering setting, not a clinical cut-off.
      </Section>
      <Section title="What this is not">
        Deltas describe the tested variants only. There is no confidence interval, minimal detectable change, or overall risk score. Recaptures stay grouped by session. A reliability claim would need a held-out participant study, which this application does not invent.
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 leading-7 text-ink/90">{children}</p>
    </section>
  );
}
