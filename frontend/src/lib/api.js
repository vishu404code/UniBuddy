import { config } from "./config";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function messageFrom(data, status) {
  if (typeof data?.detail === "string") return data.detail;
  if (status === 422) return "Check the form and try again.";
  return `Request failed (${status}).`;
}

export async function apiRequest(path, { method = "GET", body, token } = {}) {
  const headers = { Accept: "application/json" };
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (isForm) payload = body;
  else if (body !== undefined) payload = JSON.stringify(body);

  let response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "The server could not be reached. Try again shortly.");
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, messageFrom(data, response.status));
  return data;
}

export const fetchMe = (token) => apiRequest("/auth/me", { token });
export const submitRegistration = (email, fullName) =>
  apiRequest("/auth/registrations", { method: "POST", body: { email, full_name: fullName } });
