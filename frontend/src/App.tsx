import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Explore } from "./pages/Explore";
import { Catalog } from "./pages/Catalog";
import { Analyses } from "./pages/Analyses";
import { AnalysisDetail } from "./pages/AnalysisDetail";
import { Events } from "./pages/Events";
import { Copilot } from "./pages/Copilot";
import { Models } from "./pages/Models";
import { Reports } from "./pages/Reports";
import { Method } from "./pages/Method";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="explore" element={<Explore />} />
          <Route path="catalog" element={<Catalog />} />
          <Route path="analyses" element={<Analyses />} />
          <Route path="analyses/:resultId" element={<AnalysisDetail />} />
          <Route path="events" element={<Events />} />
          <Route path="copilot" element={<Copilot />} />
          <Route path="models" element={<Models />} />
          <Route path="reports" element={<Reports />} />
          <Route path="method" element={<Method />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
