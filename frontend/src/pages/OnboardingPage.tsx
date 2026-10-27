import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../session";

const FEATURES = [
  {
    title: "Know the seller",
    body: "We start with you — your company, site, and any docs you already have.",
  },
  {
    title: "Research the lead",
    body: "Then we gather public evidence on the company you want to pursue.",
  },
  {
    title: "Evidence-backed report",
    body: "You get a briefing: signals, fit, gaps, and what to say next. Facts stay tied to sources.",
  },
];

export function OnboardingPage() {
  const { seller, setSeller } = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState(seller?.name ?? "");
  const [companyName, setCompanyName] = useState(seller?.companyName ?? "");
  const [companyWebsite, setCompanyWebsite] = useState(
    seller?.companyWebsite ?? "",
  );
  const [documents, setDocuments] = useState<File[]>(seller?.documents ?? []);

  function onFiles(list: FileList | null) {
    if (!list) return;
    setDocuments((current) => [...current, ...Array.from(list)]);
  }

  function removeFile(index: number) {
    setDocuments((current) => current.filter((_, i) => i !== index));
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const site = companyWebsite.trim();
    setSeller({
      name: name.trim(),
      companyName: companyName.trim(),
      companyWebsite: /^https?:\/\//i.test(site) ? site : `https://${site}`,
      documents,
    });
    navigate("/lead");
  }

  return (
    <main className="spread">
      <section className="intro">
        <p className="eyebrow">Briefing desk</p>
        <h1>Research a company the way a careful seller would.</h1>
        <p className="lede">
          Tell us who you are. Add a lead. Watch the work unfold — your profile,
          their details, then a report you can actually use.
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
          <p>Required to match later research to what you actually sell.</p>
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
              accept=".pdf,.doc,.docx,.txt,.md"
              onChange={(e) => {
                onFiles(e.target.files);
                e.target.value = "";
              }}
            />
            Drop pitch decks, one-pagers, or ICP notes — or click to browse.
          </label>
          {documents.length > 0 ? (
            <ul className="file-list">
              {documents.map((file, index) => (
                <li key={`${file.name}-${index}`}>
                  <span>{file.name}</span>
                  <button type="button" onClick={() => removeFile(index)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <button className="primary" type="submit">
          Continue to lead
        </button>
      </form>
    </main>
  );
}
