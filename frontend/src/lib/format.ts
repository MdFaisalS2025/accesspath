export function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(2)} km`;
  }
  return `${Math.round(meters)} m`;
}

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `~${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `~${hours} h ${remMinutes} min`;
}

// Deliberately descriptive, not "probability of being accessible" --
// these are relative decision-support labels over the scoring model's
// output, not a calibrated statistical estimate. See
// docs/week6_frontend_report.md's "Confidence communication" section.
export function accessibilityBand(score: number | null): string {
  if (score === null) return "no evidence";
  if (score >= 0.8) return "few or no documented issues";
  if (score >= 0.5) return "some documented issues";
  if (score >= 0.2) return "notable documented issues";
  return "severe documented issue(s)";
}

export function confidenceBand(score: number | null): string {
  if (score === null) return "no evidence";
  if (score >= 0.5) return "well-documented";
  if (score >= 0.2) return "some evidence";
  if (score > 0) return "very limited evidence";
  return "no evidence";
}

export function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(2);
}
