import { dashboardPathForRole } from "./roles";

// Decides where a signed-in user goes. It reads only the protected UniBuddy profile
// (looked up by Auth user ID on the server). Email, provider and client-side data
// are never inputs, so a sign-in method cannot grant a role.
export function destinationAfterSignIn(profile) {
  if (!profile) return { kind: "no_access" };
  const path = dashboardPathForRole(profile.role);
  return path ? { kind: "dashboard", path } : { kind: "no_access" };
}
