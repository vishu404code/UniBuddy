import { describe, expect, it } from "vitest";
import { destinationAfterSignIn } from "./accessDecision";

describe("destinationAfterSignIn", () => {
  it("grants no access when there is no UniBuddy profile", () => {
    expect(destinationAfterSignIn(null)).toEqual({ kind: "no_access" });
    expect(destinationAfterSignIn(undefined)).toEqual({ kind: "no_access" });
  });

  it.each([
    ["student", "/student/dashboard"],
    ["faculty", "/faculty/dashboard"],
    ["authority", "/authority/dashboard"],
    ["management", "/management/dashboard"],
    ["super_admin", "/super-admin/accounts"],
  ])("sends a %s profile to its own home", (role, path) => {
    expect(destinationAfterSignIn({ role, campus_id: "c", email: "x@nst.rishihood.edu.in" })).toEqual({
      kind: "dashboard",
      path,
    });
  });

  it("treats an unknown role as no access", () => {
    expect(destinationAfterSignIn({ role: "admin" })).toEqual({ kind: "no_access" });
  });
});
