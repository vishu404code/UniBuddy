import { describe, expect, it, vi } from "vitest";
import { googleButtonOptions, googleInitOptions } from "./googleSignIn";

describe("googleInitOptions", () => {
  it("uses the public client ID and forwards only the credential", () => {
    const received = vi.fn();
    const options = googleInitOptions("client-id.apps.googleusercontent.com", received);

    options.callback({ credential: "id-token-value", select_by: "btn" });

    expect(options.client_id).toBe("client-id.apps.googleusercontent.com");
    expect(received).toHaveBeenCalledWith("id-token-value");
  });

  it("never sends a secret, role or campus from the browser", () => {
    const serialised = JSON.stringify(googleInitOptions("id", () => {}), (_key, value) =>
      typeof value === "function" ? "[fn]" : value,
    );

    expect(serialised).not.toMatch(/secret|role|campus|admin/i);
  });
});

describe("googleButtonOptions", () => {
  it("renders the standard button with no extra data", () => {
    expect(googleButtonOptions()).toEqual({ theme: "outline", size: "large", text: "continue_with", width: 320 });
  });
});
