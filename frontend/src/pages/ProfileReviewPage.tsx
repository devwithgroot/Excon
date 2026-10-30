import { FormEvent, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import {
  approveSeller,
  getExtraction,
  getSeller,
  jobFinished,
  saveSellerDraft,
  setSuggestionStatus,
  type EvidenceItem,
  type ExtractionJob,
  type FieldTrace,
  type IcpListField,
  type ProductItem,
  type ProfileListField,
  type SellerProfileOut,
  type SellerResponse,
  type ServiceItem,
  type Support,
} from "../api";
import { useSession } from "../session";

const POLL_MS = 1500;

const ICP_LABELS: Record<IcpListField, string> = {
  target_industries: "Target industries",
  geography: "Geography",
  departments: "Departments",
  decision_makers: "Decision makers",
  customer_problems: "Customer problems",
  pain_points: "Pain points",
  buying_signals: "Buying signals",
  use_cases: "Use cases",
  preferred_characteristics: "Preferred characteristics",
  exclusions: "Exclusions",
  disqualifiers: "Disqualifiers",
};

const MISSING_LABELS: Record<string, string> = {
  description: "Company description",
  industry: "Industry",
  product_or_service: "Products or services",
  customer_segment: "Customer segments",
  problem_solved: "Problems solved",
};

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function ListEditor({
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [text, setText] = useState(value.join("\n"));
  const joined = value.join("\n");
  useEffect(() => {
    setText((current) => (lines(current).join("\n") === joined ? current : joined));
  }, [joined]);
  return (
    <textarea
      rows={rows}
      value={text}
      placeholder={placeholder ?? "One item per line"}
      onChange={(event) => {
        setText(event.target.value);
        onChange(lines(event.target.value));
      }}
    />
  );
}

function Badge({ trace, support, filled }: { trace?: FieldTrace; support?: Support; filled: boolean }) {
  if (trace?.edited) return <span className="badge badge-edited">Edited by you</span>;
  if (!filled) return <span className="badge badge-missing">Not found</span>;
  const kind = trace?.support ?? support;
  if (kind === "inferred") return <span className="badge badge-inferred">Inferred · check it</span>;
  if (kind === "explicit") return <span className="badge badge-source">From sources</span>;
  return null;
}

function EvidenceToggle({ ids, index }: { ids: string[]; index: Map<string, EvidenceItem> }) {
  const [open, setOpen] = useState(false);
  const items = ids.map((id) => index.get(id)).filter((item): item is EvidenceItem => Boolean(item));
  if (!items.length) return null;
  return (
    <div className="evidence-toggle">
      <button type="button" className="ghost small" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide" : "Show"} {items.length} source{items.length === 1 ? "" : "s"}
      </button>
      {open ? (
        <ul className="evidence-list">
          {items.map((item) => (
            <EvidenceRow key={item.evidence_id} item={item} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function EvidenceRow({ item, label }: { item: EvidenceItem; label?: string }) {
  const where = [item.source_title, item.section_reference].filter(Boolean).join(" · ");
  return (
    <li>
      {label ? <strong>{label}</strong> : null}
      <blockquote>“{item.supporting_excerpt}”</blockquote>
      <span>
        {item.source_url ? (
          <a href={item.source_url} target="_blank" rel="noreferrer">
            {where || item.source_url}
          </a>
        ) : (
          where || item.source_type
        )}
        {item.support === "inferred" ? " · inferred" : ""}
      </span>
    </li>
  );
}

function Field({
  label,
  trace,
  filled,
  evidence,
  children,
  hint,
}: {
  label: string;
  trace?: FieldTrace;
  filled: boolean;
  evidence: Map<string, EvidenceItem>;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="field">
      <div className="field-head">
        <span className="field-label">{label}</span>
        <Badge trace={trace} filled={filled} />
      </div>
      {children}
      {hint ? <p className="hint">{hint}</p> : null}
      <EvidenceToggle ids={trace?.evidence_ids ?? []} index={evidence} />
    </div>
  );
}

function Section({ number, title, note, children }: { number: number; title: string; note?: string; children: ReactNode }) {
  return (
    <section className="review-section">
      <header>
        <span className="marker">{number}</span>
        <div>
          <h2>{title}</h2>
          {note ? <p className="hint">{note}</p> : null}
        </div>
      </header>
      <div className="review-body">{children}</div>
    </section>
  );
}

function Progress({ job }: { job: ExtractionJob }) {
  const failed = job.status === "failed";
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{failed ? "Extraction stopped" : "Building your company profile"}</h2>
        <p>
          {failed
            ? job.error
            : "We read your documents and website, extract facts with sources, then assemble a draft for you to review. This can take a few minutes on a local model."}
        </p>
      </div>
      <ol className="timeline-list">
        {job.stages.map((stage, index) => {
          const state =
            index < job.stage_index || job.stage === "ready_for_review"
              ? "done"
              : index === job.stage_index
                ? failed
                  ? "error"
                  : "running"
                : "pending";
          return (
            <li key={stage} data-state={state}>
              <span className="marker">{index + 1}</span>
              <div>
                <strong>{stage.replace(/_/g, " ")}</strong>
                {index === job.stage_index && job.detail ? <span>{job.detail}</span> : null}
              </div>
            </li>
          );
        })}
      </ol>
      {job.documents.length ? (
        <ul className="file-list">
          {job.documents.map((doc) => (
            <li key={doc.document_id} data-state={doc.error ? "missing" : undefined}>
              <span>{doc.filename}</span>
              <span className="hint">{doc.error ? `${doc.status}: ${doc.error}` : doc.status}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ProfileReviewPage() {
  const session = useSession();
  const { sellerId, jobId, setSellerRecord } = session;
  const navigate = useNavigate();
  const [job, setJob] = useState<ExtractionJob | null>(null);
  const [record, setRecord] = useState<SellerResponse | null>(null);
  const [form, setForm] = useState<SellerProfileOut | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!sellerId) return;
    const activeSeller = sellerId;
    let cancelled = false;
    let timer: number | undefined;

    function load(response: SellerResponse) {
      setRecord(response);
      setForm(structuredClone(response.draft));
      setDirty(false);
      setSellerRecord(response.seller_id, response.status === "approved");
    }

    async function poll(id: string) {
      try {
        const status = await getExtraction(id);
        if (cancelled) return;
        setJob(status);
        if (jobFinished(status)) {
          load(status.seller ?? (await getSeller(activeSeller)));
          return;
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Lost contact with the extraction job; retrying…");
      }
      timer = window.setTimeout(() => void poll(id), POLL_MS);
    }

    async function start() {
      try {
        const current = await getSeller(activeSeller);
        if (cancelled) return;
        const latest = current.job;
        const watch = jobId ?? latest?.job_id ?? null;
        if (latest && !jobFinished(latest) && watch) {
          setJob(latest);
          void poll(watch);
        } else {
          setJob(latest);
          load(current);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the profile");
      }
    }

    void start();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [sellerId, jobId, setSellerRecord]);

  const evidence = useMemo(
    () => new Map((form?.evidence ?? []).map((item) => [item.evidence_id, item])),
    [form?.evidence],
  );

  if (!sellerId) return <Navigate to="/" replace />;

  const running = job !== null && !jobFinished(job);
  if (running || (!form && job)) {
    return (
      <main className="narrow wide-form">
        <p className="eyebrow">Step 2 of 5 · Building your profile</p>
        <h1>Reading what you sell</h1>
        {error ? <p className="error-line">{error}</p> : null}
        {job ? <Progress job={job} /> : null}
      </main>
    );
  }
  if (!form || !record) {
    return (
      <main className="narrow">
        {error ? <p className="error-line">{error}</p> : <p className="hint">Loading the profile…</p>}
      </main>
    );
  }

  const profile = form;
  const traces = profile.traces ?? {};
  const metadata = profile.extraction_metadata;

  function edit(change: Partial<SellerProfileOut>) {
    setForm((current) => (current ? { ...current, ...change } : current));
    setDirty(true);
  }

  function editIcp(change: Partial<SellerProfileOut["icp"]>) {
    setForm((current) => (current ? { ...current, icp: { ...current.icp, ...change } } : current));
    setDirty(true);
  }

  function text(key: keyof SellerProfileOut, label: string, opts: { area?: boolean; hint?: string } = {}) {
    const value = (profile[key] as string | null) ?? "";
    return (
      <Field label={label} trace={traces[key]} filled={Boolean(value.trim())} evidence={evidence} hint={opts.hint}>
        {opts.area ? (
          <textarea rows={3} value={value} onChange={(e) => edit({ [key]: e.target.value || null })} />
        ) : (
          <input value={value} onChange={(e) => edit({ [key]: e.target.value || null })} />
        )}
      </Field>
    );
  }

  function list(key: ProfileListField, label: string, placeholder?: string) {
    return (
      <Field label={label} trace={traces[key]} filled={profile[key].length > 0} evidence={evidence}>
        <ListEditor value={profile[key]} onChange={(next) => edit({ [key]: next })} placeholder={placeholder} />
      </Field>
    );
  }

  function updateProduct(index: number, change: Partial<ProductItem>) {
    edit({ products: profile.products.map((item, i) => (i === index ? { ...item, ...change } : item)) });
  }

  function updateService(index: number, change: Partial<ServiceItem>) {
    edit({ services: profile.services.map((item, i) => (i === index ? { ...item, ...change } : item)) });
  }

  async function persist(): Promise<SellerResponse> {
    const response = await saveSellerDraft(record!.seller_id, profile);
    setRecord(response);
    setForm(structuredClone(response.draft));
    setDirty(false);
    return response;
  }

  async function onSave(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await persist();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the draft");
    } finally {
      setSaving(false);
    }
  }

  async function onApprove() {
    const named = [...profile.products, ...profile.services].filter((item) => item.name.trim());
    if (!named.length) {
      setError("Add at least one product or service before approving. Fit scoring needs it.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (dirty) await persist();
      const response = await approveSeller(record!.seller_id);
      setSellerRecord(response.seller_id, true);
      navigate("/lead");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve the profile");
    } finally {
      setSaving(false);
    }
  }

  async function onSuggestion(suggestionId: string, action: "accept" | "reject") {
    setError(null);
    try {
      const response = await setSuggestionStatus(record!.seller_id, suggestionId, action);
      setRecord(response);
      setForm((current) =>
        current
          ? { ...current, suggested_prospect_characteristics: response.draft.suggested_prospect_characteristics }
          : current,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the suggestion");
    }
  }

  const sourcesById = new Map(metadata.sources.map((source) => [source.source_id, source]));
  const usedSources = metadata.sources.filter((source) => !source.error);
  const problemSources = metadata.sources.filter((source) => source.error);
  const openIssues = metadata.validation.filter(
    (issue) => !issue.resolved && issue.severity !== "info" && issue.code !== "conflict",
  );

  return (
    <main className="narrow review">
      <p className="eyebrow">Step 2 of 5 · Approve your profile</p>
      <h1>Is this what you sell?</h1>
      <p className="lede">
        Everything below came from your documents and website. Items marked <em>inferred</em> were
        reasoned, not stated — check them. Nothing is used for lead scoring until you approve.
      </p>

      <div className={`status-banner status-${metadata.status}`}>
        <strong>
          {metadata.status === "complete"
            ? "Extraction complete"
            : metadata.status === "partial"
              ? "Extraction partly complete"
              : metadata.status === "failed"
                ? "Extraction failed — fill the profile in yourself"
                : "Manual profile"}
        </strong>
        <span>
          {record.status === "approved" ? `Approved v${record.approved_version}` : "Not approved yet"}
          {" · "}
          {Math.round((metadata.completeness ?? 0) * 100)}% complete · {usedSources.length} source
          {usedSources.length === 1 ? "" : "s"} · {profile.evidence.length} evidence item
          {profile.evidence.length === 1 ? "" : "s"}
        </span>
        {job?.error ? <span className="error-line">{job.error}</span> : null}
      </div>
      {error ? <p className="error-line">{error}</p> : null}

      <form className="stacked-sections" onSubmit={onSave}>
        <Section number={1} title="Company overview">
          <Field label="Company name" filled={Boolean(profile.company_name)} evidence={evidence}>
            <input required value={profile.company_name} onChange={(e) => edit({ company_name: e.target.value })} />
          </Field>
          {text("website_url", "Website")}
          {text("description", "Description", { area: true })}
          <div className="two-col">
            {text("industry", "Industry")}
            {text("sub_industry", "Sub-industry")}
          </div>
          <div className="two-col">
            {text("business_model", "Business model")}
            {text("company_size", "Company size", { hint: "Only filled when a source states it." })}
          </div>
          {text("market_positioning", "Market positioning")}
          {list("geography", "Geography", "One region or country per line")}
        </Section>

        <Section number={2} title="Products" note="Packaged offerings you sell. At least one product or service is required.">
          {profile.products.map((item, index) => (
            <div className="offering" key={index}>
              <div className="field-head">
                <input
                  className="offering-name"
                  value={item.name}
                  placeholder="Product name"
                  onChange={(e) => updateProduct(index, { name: e.target.value })}
                />
                <Badge support={item.support} filled />
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => edit({ products: profile.products.filter((_, i) => i !== index) })}
                >
                  Remove
                </button>
              </div>
              <textarea
                rows={2}
                placeholder="What it does"
                value={item.description ?? ""}
                onChange={(e) => updateProduct(index, { description: e.target.value || null })}
              />
              <div className="two-col">
                <label>
                  Features
                  <ListEditor rows={2} value={item.features ?? []} onChange={(next) => updateProduct(index, { features: next })} />
                </label>
                <label>
                  Target users
                  <ListEditor rows={2} value={item.target_users ?? []} onChange={(next) => updateProduct(index, { target_users: next })} />
                </label>
              </div>
              <label>
                Problems it solves
                <ListEditor
                  rows={2}
                  value={item.problems_solved ?? []}
                  onChange={(next) => updateProduct(index, { problems_solved: next })}
                />
              </label>
              <EvidenceToggle ids={item.evidence_ids ?? []} index={evidence} />
            </div>
          ))}
          <button
            type="button"
            className="ghost"
            onClick={() => edit({ products: [...profile.products, { name: "", features: [], target_users: [], problems_solved: [] }] })}
          >
            + Add product
          </button>
        </Section>

        <Section number={3} title="Services" note="Work you perform for clients.">
          {profile.services.map((item, index) => (
            <div className="offering" key={index}>
              <div className="field-head">
                <input
                  className="offering-name"
                  value={item.name}
                  placeholder="Service name"
                  onChange={(e) => updateService(index, { name: e.target.value })}
                />
                <Badge support={item.support} filled />
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => edit({ services: profile.services.filter((_, i) => i !== index) })}
                >
                  Remove
                </button>
              </div>
              <textarea
                rows={2}
                placeholder="What you deliver"
                value={item.description ?? ""}
                onChange={(e) => updateService(index, { description: e.target.value || null })}
              />
              <div className="two-col">
                <label>
                  Target customer
                  <input
                    value={item.target_customer ?? ""}
                    onChange={(e) => updateService(index, { target_customer: e.target.value || null })}
                  />
                </label>
                <label>
                  Business outcome
                  <input
                    value={item.business_outcome ?? ""}
                    onChange={(e) => updateService(index, { business_outcome: e.target.value || null })}
                  />
                </label>
              </div>
              <EvidenceToggle ids={item.evidence_ids ?? []} index={evidence} />
            </div>
          ))}
          <button
            type="button"
            className="ghost"
            onClick={() => edit({ services: [...profile.services, { name: "", use_cases: [] }] })}
          >
            + Add service
          </button>
        </Section>

        <Section number={4} title="Value and differentiation">
          {text("value_proposition", "Value proposition", { area: true })}
          {list("problems_solved", "Problems you solve")}
          {list("differentiators", "Differentiators")}
          {list("features", "Key features")}
          {list("use_cases", "Use cases")}
          {list("limitations", "Not a fit when", "Segments or situations you do not serve")}
        </Section>

        <Section number={5} title="Customers and market">
          {list("customer_segments", "Customer segments")}
          {list("industries_served", "Industries served")}
        </Section>

        <Section number={6} title="Ideal customer profile" note="A proposal built from the sections above — inferred, so adjust it to how you actually sell.">
          <Field label="Target company size" trace={traces.icp} filled={Boolean(profile.icp.company_size)} evidence={evidence}>
            <input value={profile.icp.company_size ?? ""} onChange={(e) => editIcp({ company_size: e.target.value || null })} />
          </Field>
          <div className="two-col">
            {(Object.keys(ICP_LABELS) as IcpListField[]).map((key) => (
              <label key={key}>
                {ICP_LABELS[key]}
                <ListEditor rows={2} value={profile.icp[key] ?? []} onChange={(next) => editIcp({ [key]: next })} />
              </label>
            ))}
          </div>
        </Section>

        <Section
          number={7}
          title="Suggested prospect types"
          note="Recommendations, not facts. Only accepted suggestions are used when scoring leads."
        >
          {profile.suggested_prospect_characteristics.length ? (
            <ul className="suggestions">
              {profile.suggested_prospect_characteristics.map((item) => (
                <li key={item.suggestion_id} data-status={item.status}>
                  <div className="field-head">
                    <strong>{item.prospect_type}</strong>
                    <span className={`badge badge-${item.status === "accepted" ? "source" : item.status === "rejected" ? "missing" : "inferred"}`}>
                      {item.status}
                    </span>
                  </div>
                  {item.why_relevant ? <p>{item.why_relevant}</p> : null}
                  <p className="hint">
                    {[
                      item.matching_offering && `Offering: ${item.matching_offering}`,
                      item.problem_addressed && `Problem: ${item.problem_addressed}`,
                      item.decision_makers.length && `Decision makers: ${item.decision_makers.join(", ")}`,
                      item.buying_signals.length && `Signals: ${item.buying_signals.join(", ")}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <div className="action-pair">
                    <button
                      type="button"
                      className="ghost small"
                      disabled={item.status === "accepted"}
                      onClick={() => void onSuggestion(item.suggestion_id, "accept")}
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      className="ghost small"
                      disabled={item.status === "rejected"}
                      onClick={() => void onSuggestion(item.suggestion_id, "reject")}
                    >
                      Reject
                    </button>
                  </div>
                  <EvidenceToggle ids={item.evidence_ids} index={evidence} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">No suggestions were generated.</p>
          )}
        </Section>

        <Section number={8} title="Sources, gaps and conflicts">
          {metadata.missing.length ? (
            <div className="field">
              <span className="field-label">Not found in any source</span>
              <ul className="gaps">
                {metadata.missing.map((item) => (
                  <li key={item}>
                    <span>{MISSING_LABELS[item] ?? item} — fill it in above if it applies.</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {metadata.conflicts.length ? (
            <div className="field">
              <span className="field-label">Sources disagree</span>
              <ul className="gaps">
                {metadata.conflicts.map((conflict) => (
                  <li key={conflict.field}>
                    <strong>{conflict.field.replace(/_/g, " ")}</strong>
                    {conflict.values.map((value) => (
                      <span key={value.value}>
                        “{value.value}” —{" "}
                        {value.source_ids.map((id) => sourcesById.get(id)?.name ?? id).join(", ")}
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {openIssues.length ? (
            <div className="field">
              <span className="field-label">Checks</span>
              <ul className="gaps">
                {openIssues.map((issue, index) => (
                  <li key={`${issue.code}-${issue.field}-${index}`}>
                    <span>
                      {issue.severity === "error" ? "Needs fixing: " : ""}
                      {issue.message}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="field">
            <span className="field-label">Sources read ({usedSources.length})</span>
            <ul className="file-list">
              {usedSources.map((source) => (
                <li key={source.source_id}>
                  <span>
                    {source.url ? (
                      <a href={source.url} target="_blank" rel="noreferrer">
                        {source.name}
                      </a>
                    ) : (
                      source.name
                    )}
                  </span>
                  <span className="hint">
                    {source.source_type.replace(/_/g, " ")} · {source.status.replace(/_/g, " ")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          {problemSources.length || metadata.warnings.length ? (
            <div className="field">
              <span className="field-label">Problems</span>
              <ul className="gaps">
                {problemSources.map((source) => (
                  <li key={source.source_id}>
                    <span>
                      {source.name}: {source.error}
                    </span>
                  </li>
                ))}
                {metadata.warnings.map((warning) => (
                  <li key={warning}>
                    <span>{warning}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <AllEvidence items={profile.evidence} />
        </Section>

        <div className="actions sticky-actions">
          <Link className="ghost" to="/">
            Start over
          </Link>
          <div className="action-pair">
            <button className="ghost" type="submit" disabled={saving || !dirty}>
              {saving ? "Saving…" : dirty ? "Save draft" : "Saved"}
            </button>
            <button className="primary" type="button" disabled={saving} onClick={() => void onApprove()}>
              Approve profile and continue
            </button>
          </div>
        </div>
      </form>
    </main>
  );
}

function AllEvidence({ items }: { items: EvidenceItem[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  return (
    <div className="field">
      <button type="button" className="ghost small" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide" : "Show"} all {items.length} evidence items
      </button>
      {open ? (
        <ul className="evidence-list">
          {items.map((item) => (
            <EvidenceRow
              key={item.evidence_id}
              item={item}
              label={`${item.field_key.replace("seller.", "").replace(/_/g, " ")}: ${item.extracted_value ?? ""}`}
            />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
