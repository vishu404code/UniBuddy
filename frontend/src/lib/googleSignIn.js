export const AUTH_CALLBACK_PATH = "/auth/callback";

// Hint only: Google's account chooser prefers this domain. It is not a security control.
// The server still decides access from the UniBuddy profile for the Auth user ID.
export const GOOGLE_HOSTED_DOMAIN = "nst.rishihood.edu.in";

export function googleSignInRequest(origin) {
  return {
    provider: "google",
    options: {
      redirectTo: `${origin}${AUTH_CALLBACK_PATH}`,
      queryParams: { hd: GOOGLE_HOSTED_DOMAIN },
    },
  };
}
