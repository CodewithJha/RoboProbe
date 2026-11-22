/** Bearer tokens remain scoped to this browser session (TM-01). */
const TOKEN_KEY = 'roboprobe.api-token';
export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null): void {
  if (token?.trim()) sessionStorage.setItem(TOKEN_KEY, token.trim());
  else sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event('roboprobe-token-changed'));
}
