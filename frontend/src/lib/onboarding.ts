/** First-run onboarding tour persistence. */

const TOUR_KEY = "vnss-tour-v1";

export function hasSeenTour(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === "1";
  } catch {
    return true;
  }
}

export function markTourSeen(): void {
  try {
    localStorage.setItem(TOUR_KEY, "1");
  } catch {
    /* ignore */
  }
}
