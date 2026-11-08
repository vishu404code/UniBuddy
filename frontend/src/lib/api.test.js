import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest, submitRegistration } from "./api";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status, body) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiRequest", () => {
  it("sends the bearer token only when one is given", async () => {
    const fetchMock = stubFetch(200, { ok: true });
    await apiRequest("/auth/me", { token: "t0k" });
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer t0k");

    await apiRequest("/auth/me");
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBeUndefined();
  });

  it("turns server errors into ApiError with the server's detail", async () => {
    stubFetch(403, { detail: "Only authority users can onboard students and faculty" });
    await expect(apiRequest("/provisioning/students", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 403,
      message: "Only authority users can onboard students and faculty",
    });
  });

  it("does not show raw validation objects to the user", async () => {
    stubFetch(422, { detail: [{ loc: ["body", "email"], msg: "bad", type: "value_error" }] });
    await expect(apiRequest("/auth/registrations", { method: "POST", body: {} })).rejects.toThrow(
      "Check the form and try again.",
    );
  });

  it("reports an unreachable server as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    await expect(apiRequest("/auth/me")).rejects.toBeInstanceOf(ApiError);
    await expect(apiRequest("/auth/me")).rejects.toMatchObject({ status: 0 });
  });
});

describe("submitRegistration", () => {
  it("sends only the email and full name", async () => {
    const fetchMock = stubFetch(202, { status: "received", message: "ok" });
    await submitRegistration("a@nst.rishihood.edu.in", "A B");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      email: "a@nst.rishihood.edu.in",
      full_name: "A B",
    });
  });
});
