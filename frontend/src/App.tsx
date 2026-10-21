import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/Toast";
import { IncidentDetailPage } from "./pages/IncidentDetailPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ServicesPage } from "./pages/ServicesPage";
import { SignalsPage } from "./pages/SignalsPage";

function NotFoundPage() {
  return (
    <div className="not-found">
      <p className="eyebrow">404</p>
      <h1>That view does not exist.</h1>
      <p>The Bamboo11y dashboard has five workspaces: overview, incidents, signals, services, and integrations.</p>
      <Link className="button button--primary" to="/">
        Return to overview
      </Link>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="signals" element={<SignalsPage />} />
        <Route path="services" element={<ServicesPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppRoutes />
      </ToastProvider>
    </BrowserRouter>
  );
}
