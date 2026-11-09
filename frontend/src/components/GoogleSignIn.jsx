import { useEffect, useRef } from "react";
import { googleButtonOptions, googleInitOptions, loadGoogleIdentity } from "../lib/googleSignIn";

// Renders Google's sign-in button. onCredential receives the Google ID token once.
export default function GoogleSignIn({ clientId, onCredential }) {
  const container = useRef(null);
  const handler = useRef(onCredential);
  handler.current = onCredential;

  useEffect(() => {
    if (!clientId) return undefined;
    let active = true;
    loadGoogleIdentity()
      .then((google) => {
        if (!active || !container.current) return;
        google.accounts.id.initialize(googleInitOptions(clientId, (credential) => handler.current(credential)));
        google.accounts.id.renderButton(container.current, googleButtonOptions());
      })
      .catch(() => {
        if (active && container.current) {
          container.current.textContent = "Google sign-in could not load. Check your connection and reload.";
        }
      });
    return () => {
      active = false;
    };
  }, [clientId]);

  if (!clientId) {
    return <p role="alert" className="error">Google sign-in is not configured for this site.</p>;
  }
  return <div ref={container} className="google-signin" />;
}
