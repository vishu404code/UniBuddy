import { apiRequest } from "./api";

// UniBuddy's own session token, issued after Google sign-in. Stored in this browser only.
// It is a convenience for returning users. The server checks the token on every request.
const KEY = "unibuddy.session";

export function getSessionToken() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token) {
  try {
    window.localStorage.setItem(KEY, token);
  } catch {
    // Private browsing can refuse storage. The session then lasts for this page only.
  }
}

export function clearSessionToken() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}

// Calls a protected endpoint with the signed-in user's token. The server decides what they may do.
export async function authedRequest(path, options = {}) {
  return apiRequest(path, { ...options, token: getSessionToken() });
}

// Sends multipart form data (for example a PDF upload) with the signed-in user's token.
export async function authedUpload(path, formData) {
  return authedRequest(path, { method: "POST", body: formData });
}
