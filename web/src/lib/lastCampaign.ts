/** Last visited campaign console (doc 13 §4, `g c`). */
const KEY = 'roboprobe.last-campaign';

export function getLastCampaign(): string | null {
  return sessionStorage.getItem(KEY);
}

export function setLastCampaign(id: string): void {
  sessionStorage.setItem(KEY, id);
}