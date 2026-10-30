import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { startExtraction } from "../api";
import { useSession } from "../session";

const ACCEPTED = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.json,.html,.htm";
const SUPPORTED = /\.(pdf|docx|pptx|xlsx|txt|md|markdown|csv|json|html|htm)$/i;
const MAX_FILES = 10;
const MAX_BYTES = 10_000_000;

function fileProblem(file: File): string | null {
  if (/\.(doc|ppt|xls)$/i.test(file.name)) {
    return "Legacy Office format: save it as .docx, .pptx, .xlsx or PDF.";
  }
  if (!SUPPORTED.test(file.name)) return "Unsupported file type.";
  if (file.size === 0) return "File is empty.";
  if (file.size > MAX_BYTES) return "File is larger than 10 MB.";
  return null;
}

const FEATURES = [
  {
    title: "Approve what you sell",
    body: "We extract a draft from your site. You correct it and approve it before any lead is scored.",
  },
  {
    title: "Research the lead",
    body: "Then we gather public evidence on the company you want to pursue.",
  },
  {
    title: "Fit report",
    body: "You get a scored briefing: pursue, consider, or deprioritize — with reasons tied to your approved offering.",
  },
  {
    title: "Person-wise drafts",
    body: "Then we write a LinkedIn connect note and WhatsApp for each decision-maker, from their role and the last stretch of company facts.",
  },
];

export function OnboardingPage() {
  const { seller, startOnboarding } = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState(seller?.name ?? "");
  const [companyName, setCompanyName] = useState(seller?.companyName ?? "");
  const [companyWebsite, setCompanyWebsite] = useState(
    seller?.companyWebsite ?? "",
  );
  const [documents, setDocuments] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function onFiles(list: FileList | null) {
    if (!list) return;
    setDocuments((current) => [...current, ...Array.from(list)].slice(0, MAX_FILES));
  }

  function removeFile(index: number) {
    setDocuments((current) => current.filter((_, i) => i !== index));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const site = companyWebsite.trim();
    const website = /^https?:\/\//i.test(site) ? site : `https://${site}`;
    const identity = {
      name: name.trim(),
      companyName: companyName.trim(),
      companyWebsite: website,
    };
    setSubmitting(true);
    setError(null);
    try {
      const job = await startExtraction({
        name: identity.name,
        company_name: identity.companyName,
        website_url: identity.companyWebsite,
        files: documents.filter((file) => file.size <= MAX_BYTES),
      });
      startOnboarding(identity, job.seller_id, job.job_id);
      navigate("/profile");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the extraction");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="spread">
      <section className="intro">
        <p className="eyebrow">Briefing desk</p>
        <h1>Research a company the way a careful seller would.</h1>
        <p className="lede">
          First we lock your company profile. Then we research a lead, score
          the fit, and write person-wise outreach drafts for you to review.
        </p>
        <ul className="features">
          {FEATURES.map((feature) => (
            <li key={feature.title}>
              <strong>{feature.title}</strong>
              <span>{feature.body}</span>
            </li>
          ))}
        </ul>
      </section>

      <form className="panel" onSubmit={onSubmit}>
        <div className="panel-head">
          <h2>Your company</h2>
          <p>Next screen: review the extracted profile and approve it.</p>
        </div>

        <label>
          Your name
          <input
            required
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Alex Rivera"
          />
        </label>

        <label>
          Company name
          <input
            required
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Northwind Analytics"
          />
        </label>

        <label>
          Company website
          <input
            required
            inputMode="url"
            value={companyWebsite}
            onChange={(e) => setCompanyWebsite(e.target.value)}
            placeholder="https://example.com"
          />
        </label>

        <div className="upload">
          <p className="upload-label">Documents (optional)</p>
          <label
            className="drop"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              onFiles(event.dataTransfer.files);
            }}
          >
            <input
              type="file"
              multiple
              accept={ACCEPTED}
              onChange={(e) => {
                onFiles(e.target.files);
                e.target.value = "";
              }}
            />
            Drop pitch decks, brochures, one-pagers, or ICP notes — or click to browse.
            <span className="hint">PDF, DOCX, PPTX, XLSX, TXT, MD, CSV, JSON, HTML · up to {MAX_FILES} files, 10 MB each</span>
          </label>
          {documents.length > 0 ? (
            <ul className="file-list">
              {documents.map((file, index) => {
                const problem = fileProblem(file);
                return (
                  <li key={`${file.name}-${index}`} data-state={problem ? "missing" : undefined}>
                    <span>
                      {file.name}
                      {problem ? <em className="file-problem"> — {problem} It will not be read.</em> : null}
                    </span>
                    <button type="button" onClick={() => removeFile(index)}>
                      Remove
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>

        {error ? <p className="error-line">{error}</p> : null}
        <button className="primary" type="submit" disabled={submitting}>
          {submitting ? "Uploading…" : "Build my company profile"}
        </button>
      </form>
    </main>
  );
}
