import { apiRequest } from "./api";
import { supabase } from "./supabase";

// Calls a protected endpoint with the signed-in user's token. The server decides what they may do.
export async function authedRequest(path, options = {}) {
  const token = (await supabase?.auth.getSession())?.data.session?.access_token;
  return apiRequest(path, { ...options, token });
}

// Sends multipart form data (for example a PDF upload) with the signed-in user's token.
export async function authedUpload(path, formData) {
  return authedRequest(path, { method: "POST", body: formData });
}
