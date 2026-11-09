// Google Identity Services: the sign-in button and the ID token it returns.
// The browser receives a short-lived ID token. It is sent once to the server, which
// verifies it. The client secret is never used in this app.
export const GOOGLE_IDENTITY_SCRIPT = "https://accounts.google.com/gsi/client";

let loading = null;

export function loadGoogleIdentity() {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = GOOGLE_IDENTITY_SCRIPT;
      script.async = true;
      script.onload = () => (window.google?.accounts?.id ? resolve(window.google) : reject(new Error("unavailable")));
      script.onerror = () => reject(new Error("unavailable"));
      document.head.appendChild(script);
    });
  }
  return loading;
}

export function googleInitOptions(clientId, onCredential) {
  return {
    client_id: clientId,
    callback: (response) => onCredential(response.credential),
    auto_select: false,
    cancel_on_tap_outside: true,
  };
}

export function googleButtonOptions(text = "continue_with") {
  return { theme: "outline", size: "large", text, width: 320 };
}
