import { useEffect, useState } from "react";
import { apiRequest } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

// Loads one protected endpoint with the current session token. Shows the server's numbers only.
export function useApi(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let active = true;
    (async () => {
      const token = getSessionToken();
      try {
        const data = await apiRequest(path, { token });
        if (active) setState({ data, error: null, loading: false });
      } catch (err) {
        if (active) setState({ data: null, error: err.message, loading: false });
      }
    })();
    return () => {
      active = false;
    };
  }, [path]);

  return state;
}
