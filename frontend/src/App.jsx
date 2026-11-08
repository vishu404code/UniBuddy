import { Navigate, Route, Routes } from "react-router-dom";
import RequireRole from "./components/RequireRole";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import AcceptInvitationPage from "./pages/AcceptInvitationPage";
import SetPasswordPage from "./pages/SetPasswordPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import StudentDashboard from "./pages/dashboards/StudentDashboard";
import StaffDashboard from "./pages/dashboards/StaffDashboard";
import ManagementDashboard from "./pages/dashboards/ManagementDashboard";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
      <Route path="/set-password" element={<SetPasswordPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route
        path="/student/dashboard"
        element={<RequireRole roles={["student"]}><StudentDashboard /></RequireRole>}
      />
      <Route
        path="/faculty/dashboard"
        element={<RequireRole roles={["faculty"]}><StaffDashboard /></RequireRole>}
      />
      <Route
        path="/authority/dashboard"
        element={<RequireRole roles={["authority"]}><StaffDashboard /></RequireRole>}
      />
      <Route
        path="/management/dashboard"
        element={<RequireRole roles={["management"]}><ManagementDashboard /></RequireRole>}
      />
      <Route path="*" element={<p role="alert">Page not found.</p>} />
    </Routes>
  );
}
