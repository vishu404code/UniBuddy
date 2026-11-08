import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const ROLE_LABEL = {
  student: "Student",
  faculty: "Faculty",
  authority: "Authority",
  management: "Management",
};

export default function Shell({ title, children }) {
  const { profile, signOut } = useAuth();
  const navigate = useNavigate();

  async function handleSignOut() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <header className="topbar">
        <strong>UniBuddy</strong>
        <span className="role-badge">{ROLE_LABEL[profile?.role] ?? ""}</span>
        <button type="button" className="secondary" onClick={handleSignOut}>Sign out</button>
      </header>
      <main>
        <h1>{title}</h1>
        {children}
      </main>
    </div>
  );
}
