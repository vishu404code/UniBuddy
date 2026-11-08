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
import AuthorityInvitationsPage from "./pages/authority/AuthorityInvitationsPage";
import DocumentsPage from "./pages/documents/DocumentsPage";
import ChatPage from "./pages/chat/ChatPage";
import { MyTicketsPage, StaffTicketsPage, TicketDetailPage } from "./pages/tickets/TicketsPage";
import SuperAdminAccountsPage from "./pages/superadmin/SuperAdminAccountsPage";

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
      <Route
        path="/authority/invitations"
        element={<RequireRole roles={["authority"]}><AuthorityInvitationsPage /></RequireRole>}
      />
      <Route
        path="/super-admin/accounts"
        element={<RequireRole roles={["super_admin"]}><SuperAdminAccountsPage /></RequireRole>}
      />
      <Route
        path="/faculty/documents"
        element={<RequireRole roles={["faculty"]}><DocumentsPage /></RequireRole>}
      />
      <Route
        path="/authority/documents"
        element={<RequireRole roles={["authority"]}><DocumentsPage /></RequireRole>}
      />
      <Route
        path="/faculty/tickets"
        element={<RequireRole roles={["faculty"]}><StaffTicketsPage basePath="/faculty/tickets" /></RequireRole>}
      />
      <Route
        path="/faculty/tickets/:id"
        element={<RequireRole roles={["faculty"]}><TicketDetailPage backTo="/faculty/tickets" /></RequireRole>}
      />
      <Route
        path="/authority/tickets"
        element={<RequireRole roles={["authority"]}><StaffTicketsPage basePath="/authority/tickets" /></RequireRole>}
      />
      <Route
        path="/authority/tickets/:id"
        element={<RequireRole roles={["authority"]}><TicketDetailPage backTo="/authority/tickets" /></RequireRole>}
      />
      <Route
        path="/student/chat"
        element={<RequireRole roles={["student"]}><ChatPage /></RequireRole>}
      />
      <Route
        path="/student/tickets"
        element={<RequireRole roles={["student"]}><MyTicketsPage basePath="/student/tickets" /></RequireRole>}
      />
      <Route
        path="/student/tickets/:id"
        element={<RequireRole roles={["student"]}><TicketDetailPage backTo="/student/tickets" /></RequireRole>}
      />
      <Route path="*" element={<p role="alert">Page not found.</p>} />
    </Routes>
  );
}
