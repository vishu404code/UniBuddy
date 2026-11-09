// These checks only help the user. The server enforces the rules and is the authority.
// Any email domain is accepted: Google verifies the person at sign-in.
export function isEmailAddress(email) {
  const value = (email || "").trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
