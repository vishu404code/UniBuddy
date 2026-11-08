import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { dashboardPathForRole } from "../lib/roles";

// The UI check is a convenience. FastAPI and Supabase RLS enforce the same roles on every request.
export default function RequireRole({ roles, children }) {
  const { session, profile, profileError, loading } = useAuth();

  if (loading) return <p className="status">Loading…</p>;
  if (!session) return <Navigate to="/login" replace />;
  if (!profile) return <p className="status" role="alert">{profileError ?? "Loading your profile…"}</p>;
  if (!roles.includes(profile.role)) {
    const home = dashboardPathForRole(profile.role);
    return home ? <Navigate to={home} replace /> : <p className="status" role="alert">{profileError}</p>;
  }
  return children;
}
