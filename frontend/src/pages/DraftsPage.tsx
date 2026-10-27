import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  approveOutreachDraft,
  generateRunDrafts,
  listRunDrafts,
  rejectOutreachDraft,
  saveOutreachDraft,
  type OutreachDraft,
} from "../api";
import { useSession } from "../session";

function replaceDraft(list: OutreachDraft[], next: OutreachDraft) {
  return list.map((item) => (item.draft_id === next.draft_id ? next : item));
}

function PersonDraft({
  draft,
  onChange,
}: {
  draft: OutreachDraft;
  onChange: (next: OutreachDraft) => void;
}) {
  const [connect, setConnect] = useState(draft.linkedin_connect);
  const [message, setMessage] = useState(draft.linkedin_message);
  const [whatsapp, setWhatsapp] = useState(draft.whatsapp);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setConnect(draft.linkedin_connect);
    setMessage(draft.linkedin_message);
    setWhatsapp(draft.whatsapp);
  }, [draft.draft_id, draft.version, draft.linkedin_connect, draft.linkedin_message, draft.whatsapp]);

  async function persist(
    action: "save" | "approve" | "reject",
    event?: FormEvent,
  ) {
    event?.preventDefault();
    setBusy(action);
    setError(null);
    try {
      let next = draft;
      if (action !== "reject") {
        next = await saveOutreachDraft(draft.draft_id, {
          linkedin_connect: connect,
          linkedin_message: message,
          whatsapp,
        });
      }
      if (action === "approve") {
        next = await approveOutreachDraft(draft.draft_id);
      } else if (action === "reject") {
        next = await rejectOutreachDraft(draft.draft_id);
      }
      onChange(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update draft");
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="panel person-draft" data-status={draft.status}>
      <header className="person-head">
        <div>
          <p className="eyebrow">{draft.status} · v{draft.version}</p>
          <h2>{draft.person_name}</h2>
          <p className="brief-sub">
            {[draft.person_title, draft.offering ? `Best fit: ${draft.offering}` : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        {draft.person_linkedin_url ? (
          <a href={draft.person_linkedin_url} target="_blank" rel="noreferrer">
            LinkedIn profile
          </a>
        ) : null}
      </header>
      <p>{draft.relevance}</p>
      {draft.offering_reason ? <p className="hint">{draft.offering_reason}</p> : null}
      {draft.cited_facts.length ? (
        <ul className="fact-chips">
          {draft.cited_facts.slice(0, 6).map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      ) : null}

      <form className="stacked" onSubmit={(event) => persist("save", event)}>
        <label>
          LinkedIn connect note
          <span className="optional"> {connect.length}/300</span>
          <textarea
            rows={3}
            value={connect}
            onChange={(e) => setConnect(e.target.value)}
          />
        </label>
        <label>
          LinkedIn message
          <textarea
            rows={10}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </label>
        <label>
          WhatsApp
          <textarea
            rows={4}
            value={whatsapp}
            onChange={(e) => setWhatsapp(e.target.value)}
          />
        </label>
        {error ? <p className="error-line">{error}</p> : null}
        <div className="actions">
          <button className="ghost" type="button" onClick={() => persist("reject")} disabled={!!busy}>
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
          <div className="action-pair">
            <button className="ghost" type="submit" disabled={!!busy}>
              {busy === "save" ? "Saving…" : "Save"}
            </button>
            <button className="primary" type="button" onClick={() => persist("approve")} disabled={!!busy}>
              {busy === "approve" ? "Approving…" : "Approve draft"}
            </button>
          </div>
        </div>
      </form>
    </article>
  );
}

export function DraftsPage() {
  const { seller, sellerApproved, lead, runId } = useSession();
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [skipped, setSkipped] = useState<{ name?: string; reason?: string }[]>([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    async function load() {
      try {
        const existing = await listRunDrafts(runId);
        if (cancelled) return;
        if (existing.drafts.length) {
          setDrafts(existing.drafts);
          setSkipped(existing.skipped);
          setStatus(existing.status);
          return;
        }
        setGenerating(true);
        const created = await generateRunDrafts(runId);
        if (cancelled) return;
        setDrafts(created.drafts);
        setSkipped(created.skipped);
        setStatus(created.status);
        if (created.error && !created.drafts.length) setError(created.error);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load drafts");
          setStatus("failed");
        }
      } finally {
        if (!cancelled) setGenerating(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (seller && !sellerApproved) {
    return <Navigate to="/profile" replace />;
  }
  if (!runId) {
    return (
      <main className="narrow">
        <p className="eyebrow">Step 5 · Drafts</p>
        <h1>No research run to write from</h1>
        <p className="lede">
          Finish a lead report first. Drafts are written person by person from
          that run’s evidence.
        </p>
        <Link className="primary" to="/lead" style={{ display: "inline-block" }}>
          Research a lead
        </Link>
      </main>
    );
  }

  async function regenerate() {
    if (!runId) return;
    setGenerating(true);
    setError(null);
    try {
      const created = await generateRunDrafts(runId);
      setDrafts(created.drafts);
      setSkipped(created.skipped);
      setStatus(created.status);
      if (created.error && !created.drafts.length) setError(created.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not regenerate drafts");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <main className="narrow wide-form drafts">
      <p className="eyebrow">Step 5 of 5 · Outreach drafts</p>
      <h1>Person-wise drafts</h1>
      <p className="lede">
        One LinkedIn connect note, LinkedIn message, and WhatsApp for each
        person on {lead?.companyName || "this lead"}. Copy is grounded in your
        approved offering and the last stretch of public company facts. Nothing
        is sent.
      </p>
      {generating ? <p className="hint">Writing drafts from the research run…</p> : null}
      {error ? <p className="error-line">{error}</p> : null}
      {!generating && !drafts.length ? (
        <p className="empty">
          {status === "no_recipients"
            ? "No named people on this run, so there is no one to write to."
            : "No drafts yet."}
        </p>
      ) : null}
      {drafts.map((draft) => (
        <PersonDraft
          key={draft.draft_id}
          draft={draft}
          onChange={(next) => setDrafts((current) => replaceDraft(current, next))}
        />
      ))}
      {skipped.length ? (
        <p className="hint">
          Skipped: {skipped.map((item) => item.name || item.reason).join(", ")}
        </p>
      ) : null}
      <div className="actions">
        <Link className="ghost" to="/run">
          Back to report
        </Link>
        <button className="ghost" type="button" onClick={() => void regenerate()} disabled={generating}>
          {generating ? "Writing…" : "Regenerate drafts"}
        </button>
      </div>
    </main>
  );
}
