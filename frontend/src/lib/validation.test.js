import { describe, expect, it } from "vitest";
import { isUniversityEmail, passwordProblem } from "./validation";

describe("isUniversityEmail", () => {
  it("accepts the exact university domain in any case", () => {
    expect(isUniversityEmail("Student.One@NST.rishihood.edu.in")).toBe(true);
    expect(isUniversityEmail("  x@nst.rishihood.edu.in ")).toBe(true);
  });

  it("refuses other domains, subdomains and look-alikes", () => {
    expect(isUniversityEmail("x@gmail.com")).toBe(false);
    expect(isUniversityEmail("x@mail.nst.rishihood.edu.in")).toBe(false);
    expect(isUniversityEmail("x@nst.rishihood.edu.in.evil.test")).toBe(false);
    expect(isUniversityEmail("nst.rishihood.edu.in")).toBe(false);
    expect(isUniversityEmail("")).toBe(false);
  });
});

describe("passwordProblem", () => {
  it("requires twelve characters and a matching confirmation", () => {
    expect(passwordProblem("short", "short")).toMatch(/at least 12/);
    expect(passwordProblem("long enough pass", "different one")).toMatch(/do not match/);
    expect(passwordProblem("long enough pass", "long enough pass")).toBeNull();
  });
});
