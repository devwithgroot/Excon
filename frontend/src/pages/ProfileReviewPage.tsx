import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import {
  approveSeller,
  createSeller,
  documentsFromFiles,
  extractSeller,
  saveSellerDraft,
  type SellerProfileOut,
} from "../api";
import { useSession } from "../session";

function emptyIcp() {
  return {
    target_industries: "",
    company_size: "",
    geography: "",
    departments_roles: "",
    problems: "",
    buying_signals: "",
    exclusions: "",
    preferred: "",
  };
}

function blankProfile(companyName: string, website: string, contact: string): SellerProfileOut {
  return {
    company_name: companyName,
    contact_name: contact || null,
    domain: null,
    website_url: website || null,
    industry: null,
    description: null,
    geography: null,
    size: null,
    products: null,
    services: null,
    features: null,
    problems_solved: null,
    differentiators: null,
    limitations: null,
    icp: emptyIcp(),
    status: "draft",
    version: 0,
  };
}

function mergeForm(
  current: ReturnType<typeof toForm> | null,
  incoming: ReturnType<typeof toForm>,
) {
  if (!current) return incoming;
  const next = { ...incoming, icp: { ...incoming.icp } };
  for (const [key, value] of Object.entries(current)) {
    if (key === "icp") {
      for (const [icpKey, icpValue] of Object.entries(current.icp)) {
        if (icpValue) next.icp[icpKey] = icpValue;
      }
    } else if (value) {
      (next as Record<string, unknown>)[key] = value;
    }
  }
  return next;
}

function toForm(profile: SellerProfileOut) {
  return {
    company_name: profile.company_name ?? "",
    contact_name: profile.contact_name ?? "",
    website_url: profile.website_url ?? "",
    industry: profile.industry ?? "",
    description: profile.description ?? "",
    geography: profile.geography ?? "",
    size: profile.size ?? "",
    products: profile.products ?? "",
    services: profile.services ?? "",
    features: profile.features ?? "",
    problems_solved: profile.problems_solved ?? "",
    differentiators: profile.differentiators ?? "",
    limitations: profile.limitations ?? "",
    icp: {
      ...emptyIcp(),
      ...Object.fromEntries(
        Object.entries(profile.icp ?? {}).map(([key, value]) => [key, value ?? ""]),
      ),
    },
  };
}

export function ProfileReviewPage() {
  const { seller, sellerId, setSellerRecord } = useSession();
  const navigate = useNavigate();
  const [form, setForm] = useState<ReturnType<typeof toForm> | null>(
    seller
      ? toForm(blankProfile(seller.companyName, seller.companyWebsite, seller.name))
      : null,
  );
  const [activeId, setActiveId] = useState<string | null>(sellerId);
  const [status, setStatus] = useState("draft");
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);
  const initialSellerId = useRef(sellerId);

  useEffect(() => {
    if (!seller) return;
    let cancelled = false;

    async function load() {
      setExtracting(true);
      setError(null);
      try {
        const docs = await documentsFromFiles(seller.documents);
        const payload = await extractSeller({
          name: seller.name,
          company_name: seller.companyName,
          website_url: seller.companyWebsite,
          documents: docs,
        });
        if (cancelled) return;
        initialSellerId.current = payload.seller_id;
        setSellerRecord(payload.seller_id, false);
        setActiveId(payload.seller_id);
        setForm((current) => mergeForm(current, toForm(payload.draft)));
        setStatus(payload.status);
        setVersion(payload.approved_version);
      } catch (err) {
        if (!cancelled) {
          setError(
            "Could not finish reading the website. Fill anything blank, then approve.",
          );
        }
      } finally {
        if (!cancelled) setExtracting(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [seller, setSellerRecord]);

  if (!seller) {
    return <Navigate to="/" replace />;
  }

  function setField(key: keyof ReturnType<typeof toForm>, value: string) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  }

  function setIcp(key: string, value: string) {
    setForm((current) =>
      current ? { ...current, icp: { ...current.icp, [key]: value } } : current,
    );
  }

  function asProfile(): SellerProfileOut {
    const current = form!;
    const blankToNull = (value: string) => value.trim() || null;
    return {
      company_name: current.company_name.trim(),
      contact_name: blankToNull(current.contact_name),
      domain: null,
      website_url: blankToNull(current.website_url),
      industry: blankToNull(current.industry),
      description: blankToNull(current.description),
      geography: blankToNull(current.geography),
      size: blankToNull(current.size),
      products: blankToNull(current.products),
      services: blankToNull(current.services),
      features: blankToNull(current.features),
      problems_solved: blankToNull(current.problems_solved),
      differentiators: blankToNull(current.differentiators),
      limitations: blankToNull(current.limitations),
      icp: {
        target_industries: blankToNull(current.icp.target_industries),
        company_size: blankToNull(current.icp.company_size),
        geography: blankToNull(current.icp.geography),
        departments_roles: blankToNull(current.icp.departments_roles),
        problems: blankToNull(current.icp.problems),
        buying_signals: blankToNull(current.icp.buying_signals),
        exclusions: blankToNull(current.icp.exclusions),
        preferred: blankToNull(current.icp.preferred),
      },
      status: "draft",
      version,
    };
  }

  async function ensureSellerId(): Promise<string> {
    if (activeId) return activeId;
    const payload = await createSeller({
      name: seller.name,
      company_name: form?.company_name || seller.companyName,
      website_url: form?.website_url || seller.companyWebsite,
      profile: form ? asProfile() : undefined,
    });
    setSellerRecord(payload.seller_id, false);
    setActiveId(payload.seller_id);
    return payload.seller_id;
  }

  async function onSave(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const id = await ensureSellerId();
      const payload = await saveSellerDraft(id, asProfile());
      setForm(toForm(payload.draft));
      setStatus(payload.status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save draft");
    } finally {
      setSaving(false);
    }
  }

  async function onApprove() {
    if (!form) return;
    if (!form.products.trim() && !form.services.trim()) {
      setError("Add at least one product or service before approving. Scoring needs that.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const id = await ensureSellerId();
      await saveSellerDraft(id, asProfile());
      const payload = await approveSeller(id);
      setSellerRecord(payload.seller_id, true);
      setStatus(payload.status);
      setVersion(payload.approved_version);
      navigate("/lead");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve profile");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="narrow wide-form">
      <p className="eyebrow">Step 2 of 4 · Approve your profile</p>
      <h1>Is this what you sell?</h1>
      <p className="lede">
        Check the extracted facts. Fill anything blank. You cannot research a
        lead until you approve this profile — that is what fit scoring uses.
      </p>
      {extracting ? (
        <p className="hint">Reading your website and documents… you can still edit the fields below.</p>
      ) : null}
      {error ? <p className="error-line">{error}</p> : null}
      {form ? (
        <form className="panel stacked" onSubmit={onSave}>
          <p className="hint">
            Status: {status}
            {version ? ` · approved v${version}` : " · not approved yet"}
          </p>
          <label>
            Company name
            <input
              required
              value={form.company_name}
              onChange={(e) => setField("company_name", e.target.value)}
            />
          </label>
          <label>
            Website
            <input
              value={form.website_url}
              onChange={(e) => setField("website_url", e.target.value)}
            />
          </label>
          <label>
            Industry
            <input
              value={form.industry}
              onChange={(e) => setField("industry", e.target.value)}
            />
          </label>
          <label>
            Description
            <textarea
              rows={3}
              value={form.description}
              onChange={(e) => setField("description", e.target.value)}
            />
          </label>
          <label>
            Products <span className="optional">(required to approve)</span>
            <textarea
              rows={3}
              value={form.products}
              onChange={(e) => setField("products", e.target.value)}
              placeholder="What you sell, in plain words"
            />
          </label>
          <label>
            Services
            <textarea
              rows={2}
              value={form.services}
              onChange={(e) => setField("services", e.target.value)}
            />
          </label>
          <label>
            Problems you solve
            <textarea
              rows={2}
              value={form.problems_solved}
              onChange={(e) => setField("problems_solved", e.target.value)}
            />
          </label>
          <label>
            Differentiators
            <input
              value={form.differentiators}
              onChange={(e) => setField("differentiators", e.target.value)}
            />
          </label>
          <label>
            Not a fit when
            <input
              value={form.limitations}
              onChange={(e) => setField("limitations", e.target.value)}
            />
          </label>
          <h2>Ideal customer</h2>
          <label>
            Target industries
            <input
              value={form.icp.target_industries}
              onChange={(e) => setIcp("target_industries", e.target.value)}
              placeholder="logistics, manufacturing, fintech"
            />
          </label>
          <label>
            Target company size
            <input
              value={form.icp.company_size}
              onChange={(e) => setIcp("company_size", e.target.value)}
            />
          </label>
          <label>
            Geography
            <input
              value={form.icp.geography}
              onChange={(e) => setIcp("geography", e.target.value)}
            />
          </label>
          <label>
            Departments / roles to reach
            <input
              value={form.icp.departments_roles}
              onChange={(e) => setIcp("departments_roles", e.target.value)}
            />
          </label>
          <label>
            Buying signals you care about
            <input
              value={form.icp.buying_signals}
              onChange={(e) => setIcp("buying_signals", e.target.value)}
            />
          </label>
          <label>
            Exclusions
            <input
              value={form.icp.exclusions}
              onChange={(e) => setIcp("exclusions", e.target.value)}
            />
          </label>
          <div className="actions">
            <Link className="ghost" to="/">
              Back
            </Link>
            <div className="action-pair">
              <button className="ghost" type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save draft"}
              </button>
              <button
                className="primary"
                type="button"
                disabled={saving}
                onClick={() => void onApprove()}
              >
                Approve profile and continue
              </button>
            </div>
          </div>
        </form>
      ) : (
        <p className="hint">Preparing the profile form…</p>
      )}
    </main>
  );
}
