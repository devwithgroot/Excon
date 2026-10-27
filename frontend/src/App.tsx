import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { LeadPage } from "./pages/LeadPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { RunPage } from "./pages/RunPage";
import { SessionProvider } from "./session";

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/" element={<OnboardingPage />} />
            <Route path="/lead" element={<LeadPage />} />
            <Route path="/run" element={<RunPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
