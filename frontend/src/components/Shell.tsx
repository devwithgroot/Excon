import { Link, Outlet } from "react-router-dom";

export function Shell() {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="wordmark">
          Excon
        </Link>
        <span className="topbar-note">Sales intelligence</span>
      </header>
      <Outlet />
    </div>
  );
}
