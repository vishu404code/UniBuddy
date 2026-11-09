import { describe, expect, it } from "vitest";
import { isEmailAddress } from "./validation";

describe("isEmailAddress", () => {
  it("accepts any well-formed address, from any domain", () => {
    expect(isEmailAddress("Student.One@NST.rishihood.edu.in")).toBe(true);
    expect(isEmailAddress("someone@gmail.com")).toBe(true);
    expect(isEmailAddress("  x@example.org ")).toBe(true);
  });

  it("rejects malformed addresses", () => {
    expect(isEmailAddress("")).toBe(false);
    expect(isEmailAddress("no-at-sign.example.com")).toBe(false);
    expect(isEmailAddress("two@@example.com")).toBe(false);
    expect(isEmailAddress("space in@example.com")).toBe(false);
  });
});
