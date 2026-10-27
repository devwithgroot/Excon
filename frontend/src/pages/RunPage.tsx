import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import {
  createResearchRun,
  createRunReport,
  documentsFromFiles,
  type FieldValue,
  type LeadReport,
  type ResearchRunResponse,
} from "../api";
import {
  fromStoredSeller,
  readStored,
  useSession,
  type LeadTarget,
  type SellerProfile,
} from "../session";

const STEPS = [
  {
    id: "seller-data",
    title: "Collecting your data",
    detail: "Reading the company site and any documents you attached.",
  },
  {
    id: "seller-summary",
    title: "Summarizing your profile",
    detail: "Products, positioning, and who you typically sell to.",
  },
  {
    id: "lead-data",
    title: "Collecting company details",
    detail: "Public pages, news, and business signals for the lead.",
  },
  {
    id: "lead-report",
    title: "Building the intelligence report",
    detail: "Fit, evidence, gaps, and a recommended next step.",
  },
] as const;

type StepState = "pending" | "running" | "done" | "error";

type RunLocationState = {
  seller?: SellerProfile;
  lead?: LeadTarget;
};

function fieldLabel(key: string) {
  return key.replace(/_/g, " ");
}

function FieldRow({ label, field }: { label: string; field: FieldValue }) {
  const missing = field.status !== "supported" || !field.value;
  return (
    <li data-state={missing ? "missing" : "supported"}>
      <strong>{fieldLabel(label)}</strong>
      <span>{missing ? "Not found this run" : field.value}</span>
    </li>
  );
}

export function RunPage() {
  const session = useSession();
  const location = useLocation();
  const navState = (location.state ?? {}) as RunLocationState;
  const stored = readStored();
  const seller =
    session.seller ??
    navState.seller ??
    fromStoredSeller(stored.seller);
  const lead = session.lead ?? navState.lead ?? stored.lead;
  const [statuses, setStatuses] = useState<StepState[]>(
    STEPS.map((_, index) => (index === 0 ? "running" : "pending")),
  );
  const [result, setResult] = useState<ResearchRunResponse | null>(null);
  const [report, setReport] = useState<LeadReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!seller || !lead) return;
    const currentSeller = seller;
    const currentLead = lead;
    let cancelled = false;
    const started = Date.now();

    const tick = window.setInterval(() => {
      const elapsed = Date.now() - started;
      const index = Math.min(STEPS.length - 1, Math.floor(elapsed / 4000));
      setStatuses((current) => {
        if (current.every((status) => status === "done" || status === "error")) {
          return current;
        }
        return STEPS.map((_, i) => {
          if (i < index) return "done";
          if (i === index) return "running";
          return "pending";
        });
      });
    }, 800);

    async function run() {
      try {
        const documents = await documentsFromFiles(currentSeller.documents);
        const payload = await createResearchRun({
          lead: {
            company_name: currentLead.companyName,
            website_url: currentLead.companyWebsite,
            company_domain: currentLead.companyDomain,
          },
          seller: session.sellerId
            ? undefined
            : {
                name: currentSeller.name,
                company_name: currentSeller.companyName,
                website_url: currentSeller.companyWebsite,
                documents,
              },
          seller_id: session.sellerId ?? undefined,
        });
        if (cancelled) return;
        session.setRunId(payload.run_id);
        setResult(payload);
        try {
          const briefing = await createRunReport(payload.run_id);
          if (!cancelled) setReport(briefing);
        } catch {
          if (!cancelled) setReport(null);
        }
        setStatuses(STEPS.map(() => "done"));
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Research failed");
        setStatuses(STEPS.map((_, index) => (index === 0 ? "error" : "pending")));
      } finally {
        window.clearInterval(tick);
      }
    }

    void run();
    return () => {
      cancelled = true;
      window.clearInterval(tick);
    };
  }, [seller, lead, session.sellerId, session.setRunId]);

  const collected = result?.collected;
  const companyEntries = useMemo(
    () => Object.entries(collected?.company ?? {}),
    [collected],
  );
  const signalEntries = useMemo(
    () => Object.entries(collected?.signals ?? {}),
    [collected],
  );

  if (seller && !session.sellerApproved) {
    return <Navigate to="/profile" replace />;
  }

  if (!seller || !lead) {
    return (
      <main className="narrow">
        <p className="eyebrow">Research run</p>
        <h1>Nothing to run yet</h1>
        <p className="lede">
          Start with your company details, then enter a lead. This page shows
          the workflow after that.
        </p>
        <Link className="primary" to="/" style={{ display: "inline-block" }}>
          Go to start
        </Link>
      </main>
    );
  }

  const complete = statuses.every((status) => status === "done") && result;
  const activeIndex = statuses.findIndex((status) => status === "running");
  const profile = result?.seller_profile;

  return (
    <main className="run">
      <aside className="timeline">
        <p className="eyebrow">Live run</p>
        <h1>
          {seller.companyName}
          <span> → </span>
          {lead.companyName}
        </h1>
        <ol>
          {STEPS.map((step, index) => (
            <li key={step.id} data-state={statuses[index]}>
              <span className="marker">{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.detail}</span>
              </div>
            </li>
          ))}
        </ol>
        <p className="status-line">
          {error
            ? "The orchestrator could not finish this run."
            : complete
              ? `Run ${result.status}. Report is on the right.`
              : activeIndex >= 0
                ? STEPS[activeIndex].title
                : "Starting…"}
        </p>
        {result ? (
          <p className="hint">
            Tools used: {result.tools_used.join(", ") || "none"}
          </p>
        ) : null}
        {complete ? (
          <Link className="primary" to="/drafts" style={{ display: "inline-block" }}>
            Write person-wise drafts
          </Link>
        ) : null}
        <Link className="ghost" to="/lead">
          Research another lead
        </Link>
      </aside>

      <section className="report" aria-live="polite">
        {error ? (
          <div className="report-wait">
            <p className="eyebrow">Failed</p>
            <h2>Research did not finish</h2>
            <p>{error}</p>
          </div>
        ) : !complete || !collected ? (
          <div className="report-wait">
            <p className="eyebrow">Working</p>
            <h2>Assembling the briefing</h2>
            <p>
              The LangGraph orchestrator is calling research tools and writing
              the run to Postgres. Missing facts stay missing.
            </p>
          </div>
        ) : (
          <article className="brief">
            <header>
              <p className="eyebrow">
                Intelligence report · {result.status}
                {report ? ` · ${report.scores.recommendation}` : ""}
              </p>
              <h2>{lead.companyName}</h2>
              <p className="brief-sub">
                Prepared for {seller.name} at {seller.companyName}
              </p>
            </header>

            {report ? (
              <section className="score-block">
                <h3>Should you pursue this lead?</h3>
                <p className={`reco reco-${report.scores.recommendation}`}>
                  {report.scores.recommendation} · {report.scores.overall}/100
                </p>
                <p>{report.scores.recommendation_reason}</p>
                <ul className="score-grid">
                  {(["fit", "qualification", "completeness", "evidence_quality", "contact_relevance"] as const).map(
                    (key) => {
                      const item = report.scores[key];
                      return (
                        <li key={key}>
                          <strong>
                            {item.label} · {item.score}
                          </strong>
                          <span>{item.reasons[0]}</span>
                        </li>
                      );
                    },
                  )}
                </ul>
                <h3>Why it may be a fit</h3>
                <ul className="reasons">
                  {report.why_fit.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <h3>Why it may not be</h3>
                <ul className="reasons">
                  {report.why_not.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                {report.product_matches.length ? (
                  <>
                    <h3>Offerings that match</h3>
                    <ul className="reasons">
                      {report.product_matches.map((item) => (
                        <li key={item.offering}>
                          <strong>{item.offering}</strong> — {item.reason}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
                <p>
                  <strong>Next step.</strong> {report.recommended_action}
                </p>
                <p>
                  <strong>Conversation angle.</strong> {report.conversation_angle}
                </p>
              </section>
            ) : null}

            <section>
              <h3>Your company</h3>
              {profile ? (
                <ul className="facts">
                  <li data-state={profile.products ? "supported" : "missing"}>
                    <strong>products</strong>
                    <span>{profile.products || "Not extracted this run"}</span>
                  </li>
                  <li data-state={profile.description ? "supported" : "missing"}>
                    <strong>description</strong>
                    <span>{profile.description || "Not extracted this run"}</span>
                  </li>
                </ul>
              ) : (
                <p>Seller context was not stored for this run.</p>
              )}
            </section>

            <section>
              <h3>Overview</h3>
              <ul className="facts">
                {companyEntries.map(([key, field]) => (
                  <FieldRow key={key} label={key} field={field} />
                ))}
              </ul>
            </section>

            <section>
              <h3>Signals</h3>
              <ul className="facts">
                {signalEntries.map(([key, field]) => (
                  <FieldRow key={key} label={key} field={field} />
                ))}
              </ul>
            </section>

            <section>
              <h3>News</h3>
              {collected.news.length ? (
                <ul className="news-list">
                  {collected.news.map((item) => (
                    <li key={item.evidence_id}>
                      <a href={item.url} target="_blank" rel="noreferrer">
                        {item.title}
                      </a>
                      <span>{item.excerpt}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">No usable news in this run.</p>
              )}
            </section>

            <section>
              <h3>People</h3>
              {collected.people.length ? (
                <p className="hint">
                  Drafts for these people are written on the next screen.
                </p>
              ) : null}
              {collected.people.length ? (
                <ul className="people-list">
                  {collected.people.map((person) => (
                    <li key={person.evidence_id}>
                      <strong>{person.name}</strong>
                      <span>
                        {[person.title, person.email, person.phone]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      {person.linkedin_url ? (
                        <a href={person.linkedin_url} target="_blank" rel="noreferrer">
                          LinkedIn
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">No decision-makers found this run.</p>
              )}
            </section>

            <section>
              <h3>Gaps and uncertainties</h3>
              {result.gap_decisions.length ? (
                <ul className="gaps">
                  {result.gap_decisions.map((decision) => (
                    <li key={decision.field}>
                      <strong>{decision.field}</strong>
                      <span>
                        {decision.retried
                          ? decision.left_missing
                            ? "Retried once; still missing."
                            : "Retried and filled."
                          : "Left missing."}{" "}
                        {decision.reason}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">No gap decisions recorded.</p>
              )}
              {result.missing.length ? (
                <p className="hint">
                  Still missing: {result.missing.join(", ")}
                </p>
              ) : (
                <p className="hint">Every tracked field has supporting evidence.</p>
              )}
            </section>
          </article>
        )}
      </section>
    </main>
  );
}
