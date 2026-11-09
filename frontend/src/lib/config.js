export const config = {
  // Public OAuth client ID for Google sign-in. It is not a secret. The client secret is never used here.
  googleClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID || "",
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1",
};
