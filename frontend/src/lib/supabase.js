import { createClient } from "@supabase/supabase-js";
import { config } from "./config";

export const supabaseConfigured = Boolean(config.supabaseUrl && config.supabasePublishableKey);

export const supabase = supabaseConfigured
  ? createClient(config.supabaseUrl, config.supabasePublishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
    })
  : null;
