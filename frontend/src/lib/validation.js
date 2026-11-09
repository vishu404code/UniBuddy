// These checks only help the user. The server enforces the same rules and is the authority.
export const UNIVERSITY_DOMAIN = "nst.rishihood.edu.in";
export const MIN_PASSWORD_LENGTH = 12;

export function isUniversityEmail(email) {
  const value = (email || "").trim().toLowerCase();
  const at = value.lastIndexOf("@");
  return at > 0 && value.slice(at + 1) === UNIVERSITY_DOMAIN;
}

export function passwordProblem(password, confirmation) {
  if ((password || "").length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password !== confirmation) return "The two passwords do not match.";
  return null;
}
