import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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

type StepState = "pending" | "running" | "done";

type RunLocationState = {
  seller?: SellerProfile;
  lead?: LeadTarget;
};

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

  useEffect(() => {
    if (!seller || !lead) return;
    const timers: number[] = [];
    STEPS.forEach((_, index) => {
      timers.push(
        window.setTimeout(() => {
          setStatuses((current) =>
            current.map((_, i) => {
              if (i < index) return "done";
              if (i === index) return "running";
              return "pending";
            }),
          );
        }, index * 1800),
      );
    });
    timers.push(
      window.setTimeout(() => {
        setStatuses(STEPS.map(() => "done"));
      }, STEPS.length * 1800),
    );
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [seller, lead]);

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

  const complete = statuses.every((status) => status === "done");
  const activeIndex = statuses.findIndex((status) => status === "running");

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
          {complete
            ? "Run complete. Report is on the right."
            : activeIndex >= 0
              ? STEPS[activeIndex].title
              : "Starting…"}
        </p>
        <Link className="ghost" to="/lead">
          Research another lead
        </Link>
      </aside>

      <section className="report" aria-live="polite">
        {!complete ? (
          <div className="report-wait">
            <p className="eyebrow">Working</p>
            <h2>Assembling the briefing</h2>
            <p>
              This screen will fill with the live report once research is
              connected. For now you are seeing the workflow and the layout.
            </p>
          </div>
        ) : (
          <article className="brief">
            <header>
              <p className="eyebrow">Intelligence report · layout preview</p>
              <h2>{lead.companyName}</h2>
              <p className="brief-sub">
                Prepared for {seller.name} at {seller.companyName}
              </p>
            </header>

            <section>
              <h3>Overview</h3>
              <p>
                Company identity, industry, size, and what they appear to be
                doing right now. Live extraction will write this from sources.
              </p>
            </section>

            <section>
              <h3>Signals</h3>
              <p>
                Hiring, expansion, funding, technology, and strategy — only
                where evidence exists. Missing items stay marked unknown.
              </p>
            </section>

            <section>
              <h3>Fit with {seller.companyName}</h3>
              <p>
                Why this lead may or may not need what you sell, using your
                approved profile
                {seller.documents.length
                  ? ` and ${seller.documents.length} uploaded document${
                      seller.documents.length === 1 ? "" : "s"
                    }.`
                  : "."}
              </p>
            </section>

            <section>
              <h3>Gaps and uncertainties</h3>
              <p>
                Fields we could not support with sources. The report will not
                invent them.
              </p>
            </section>

            <section>
              <h3>Recommended next step</h3>
              <p>
                Who to speak with and a first conversation angle, once people
                search is wired in.
              </p>
            </section>
          </article>
        )}
      </section>
    </main>
  );
}
