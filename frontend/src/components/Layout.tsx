import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import type { Health } from "../api/types";
import { Logo } from "./Logo";

const NAV = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/explore", label: "Explore", icon: "map" },
  { to: "/catalog", label: "Catalog", icon: "database" },
  { to: "/analyses", label: "Analyses", icon: "pulse" },
  { to: "/events", label: "Events", icon: "target" },
  { to: "/copilot", label: "Copilot", icon: "spark" },
  { to: "/models", label: "Models", icon: "chip" },
  { to: "/reports", label: "Reports", icon: "document" },
  { to: "/method", label: "Method", icon: "book" },
];

function Icon({ name }: { name: string }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "overview":
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      );
    case "map":
      return (
        <svg {...common}>
          <path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2Z" />
          <path d="M9 4v14M15 6v14" />
        </svg>
      );
    case "database":
      return (
        <svg {...common}>
          <ellipse cx="12" cy="5" rx="8" ry="3" />
          <path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
          <path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7" />
        </svg>
      );
    case "pulse":
      return (
        <svg {...common}>
          <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
        </svg>
      );
    case "target":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
        </svg>
      );
    case "spark":
      return (
        <svg {...common}>
          <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
          <circle cx="12" cy="12" r="2.4" />
        </svg>
      );
    case "chip":
      return (
        <svg {...common}>
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
        </svg>
      );
    case "document":
      return (
        <svg {...common}>
          <path d="M6 2h8l4 4v16H6Z" />
          <path d="M14 2v5h5M9 12h6M9 16h6" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5Z" />
          <path d="M4 17.5h16M8 7h8M8 11h6" />
        </svg>
      );
  }
}

function DataMode({ health }: { health: Health | null }) {
  if (!health) return <span className="topbar-mode">API connecting…</span>;
  const mode = health.demo_mode.effective_data_mode;
  return (
    <span className={`topbar-mode mode-${mode.toLowerCase()}`}>
      <span className="dot" /> {mode === "DEMO" ? "Demo data" : mode === "LIVE" ? "Live data" : mode.replaceAll("_", " ")}
    </span>
  );
}

export function Layout() {
  const { data: health, error } = useApi<Health>("/health");
  const demo = health?.demo_mode.banner;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">SARVEX</div>
            <div className="brand-sub">NISAR surface intelligence</div>
          </div>
        </div>

        <nav className="nav" aria-label="Primary">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="engine-status">
            <span className={`status-dot${error ? " is-bad" : health ? " is-good" : ""}`} />
            <div>
              <div>{error ? "API unreachable" : health ? "Engine online" : "Connecting…"}</div>
              <small>{health ? `${health.database.backend} · ${health.object_storage.backend}` : "waiting for health probe"}</small>
            </div>
          </div>
          <a className="foot-link" href="/api/v1/health" target="_blank" rel="noreferrer">
            Service health ↗
          </a>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-kicker">Mission console</span>
            <DataMode health={health} />
          </div>
          <div className="topbar-actions">
            <a className="ghost-link" href="/api/docs" target="_blank" rel="noreferrer">
              API docs
            </a>
            <a className="ghost-link" href="/api/openapi.json" target="_blank" rel="noreferrer">
              OpenAPI
            </a>
            <span className="version-pill">{health ? `v${health.version}` : "v1"} · evidence-first</span>
          </div>
        </header>

        {demo ? (
          <div className="demo-banner" role="status">
            <span className="demo-tag">DEMO MODE</span>
            <span>{demo}</span>
            <span className="demo-banner-tail">
              Every fixture is synthetic, labelled, and never presented as NASA/ISRO data.
            </span>
          </div>
        ) : null}

        <main className="page">
          <Outlet />
        </main>

        <footer className="app-footer">
          <span>SARVEX 1.0 · measurements are derived, explanations are cited.</span>
          <span>
            {health?.offline_mode ? "Offline-safe providers active" : "Network providers enabled"} ·{" "}
            {health?.worker.mode.replaceAll("_", " ")}
          </span>
        </footer>
      </div>
    </div>
  );
}
