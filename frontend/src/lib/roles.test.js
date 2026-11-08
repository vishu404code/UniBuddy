import { describe, expect, it } from "vitest";
import { dashboardPathForRole } from "./roles";

describe("dashboardPathForRole", () => {
  it.each([
    ["student", "/student/dashboard"],
    ["faculty", "/faculty/dashboard"],
    ["authority", "/authority/dashboard"],
    ["management", "/management/dashboard"],
  ])("sends %s to its own dashboard", (role, path) => {
    expect(dashboardPathForRole(role)).toBe(path);
  });

  it("does not send an unknown role anywhere", () => {
    expect(dashboardPathForRole("super_admin")).toBeNull();
    expect(dashboardPathForRole(undefined)).toBeNull();
  });
});
