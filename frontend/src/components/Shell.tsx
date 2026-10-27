import { Link, NavLink, Outlet } from "react-router-dom";

const STEPS = [
  { to: "/", label: "Your company" },
  { to: "/profile", label: "Approve profile" },
  { to: "/lead", label: "Lead" },
  { to: "/run", label: "Report" },
  { to: "/drafts", label: "Drafts" },
];

export function Shell() {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="wordmark">
          Excon
        </Link>
        <nav className="step-nav" aria-label="Workflow">
          {STEPS.map((step) => (
            <NavLink key={step.to} to={step.to} end={step.to === "/"}>
              {step.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
