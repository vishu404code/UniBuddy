import { describe, expect, it } from "vitest";
import { AUTH_CALLBACK_PATH, GOOGLE_HOSTED_DOMAIN, googleSignInRequest } from "./googleSignIn";

describe("googleSignInRequest", () => {
  it("requests Google and returns to the app's callback route", () => {
    const request = googleSignInRequest("http://localhost:5173");

    expect(request.provider).toBe("google");
    expect(request.options.redirectTo).toBe("http://localhost:5173/auth/callback");
    expect(AUTH_CALLBACK_PATH).toBe("/auth/callback");
  });

  it("only hints the campus domain and never carries a role", () => {
    const request = googleSignInRequest("https://example.test");

    expect(request.options.queryParams).toEqual({ hd: GOOGLE_HOSTED_DOMAIN });
    expect(JSON.stringify(request)).not.toMatch(/role|admin|authority|faculty|student/i);
  });
});
