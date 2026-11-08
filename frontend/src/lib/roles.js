export const ROLE_HOME = {
  student: "/student/dashboard",
  faculty: "/faculty/dashboard",
  authority: "/authority/dashboard",
  management: "/management/dashboard",
  super_admin: "/super-admin/accounts",
};

export function dashboardPathForRole(role) {
  return ROLE_HOME[role] ?? null;
}
