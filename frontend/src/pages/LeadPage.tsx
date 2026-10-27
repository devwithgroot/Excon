import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useSession } from "../session";

export function LeadPage() {
  const { seller, lead, setLead } = useSession();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState(lead?.companyName ?? "");

  if (!seller) {
    return <Navigate to="/" replace />;
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const nextLead = { companyName: companyName.trim() };
    setLead(nextLead);
    navigate("/run", { state: { lead: nextLead, seller } });
  }

  return (
    <main className="narrow">
      <p className="eyebrow">Step 2 of 2</p>
      <h1>Who should we research?</h1>
      <p className="lede">
        Enter the company or lead you want a briefing on. We will use{" "}
        <strong>{seller.companyName}</strong> as the seller context.
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
        <p className="hint">
          A name is enough for now. Website and extra fields can come later.
        </p>
        <div className="actions">
          <Link className="ghost" to="/">
            Back
          </Link>
          <button className="primary" type="submit">
            Start research
          </button>
        </div>
      </form>
    </main>
  );
}
