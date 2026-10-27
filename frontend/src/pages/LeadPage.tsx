import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useSession } from "../session";

export function LeadPage() {
  const { seller, sellerId, sellerApproved, lead, setLead } = useSession();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState(lead?.companyName ?? "");
  const [companyWebsite, setCompanyWebsite] = useState(lead?.companyWebsite ?? "");

  if (!seller) {
    return <Navigate to="/" replace />;
  }
  if (!sellerApproved) {
    return <Navigate to="/profile" replace />;
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const site = companyWebsite.trim();
    const nextLead = {
      companyName: companyName.trim(),
      companyWebsite: site
        ? /^https?:\/\//i.test(site)
          ? site
          : `https://${site}`
        : undefined,
    };
    setLead(nextLead);
    navigate("/run", { state: { lead: nextLead, seller } });
  }

  return (
    <main className="narrow">
      <p className="eyebrow">Step 3 of 5 · Lead</p>
      <h1>Who should we research?</h1>
      <p className="lede">
        Scoring will use your approved profile for <strong>{seller.companyName}</strong>
        {sellerId ? "." : "."}
      </p>

      <form className="panel stacked" onSubmit={onSubmit}>
        <label>
          Company or lead name
          <input
            required
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Acme Logistics"
            autoFocus
          />
        </label>
        <label>
          Company website <span className="optional">(optional)</span>
          <input
            inputMode="url"
            value={companyWebsite}
            onChange={(e) => setCompanyWebsite(e.target.value)}
            placeholder="https://acme.com"
          />
        </label>
        <p className="hint">
          A name is enough. A website helps the website tool crawl about and
          locations pages.
        </p>
        <div className="actions">
          <Link className="ghost" to="/profile">
            Back to profile
          </Link>
          <button className="primary" type="submit">
            Start research
          </button>
        </div>
      </form>
    </main>
  );
}
