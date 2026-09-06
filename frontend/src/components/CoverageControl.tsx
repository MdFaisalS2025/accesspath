export interface CoverageVisibility {
  labeled: boolean;
  unknown: boolean;
  lowConfidence: boolean;
  disputed: boolean;
  labels: boolean;
}

interface CoverageControlProps {
  visibility: CoverageVisibility;
  onChange: (visibility: CoverageVisibility) => void;
  onLoadForView: () => void;
  loading: boolean;
  disabledReason: string | null;
}

const OPTIONS: { key: keyof CoverageVisibility; label: string; swatch: string }[] = [
  { key: "labeled", label: "Labeled segments", swatch: "coverage-swatch--labeled" },
  { key: "unknown", label: "Unknown segments (no evidence)", swatch: "coverage-swatch--unknown" },
  { key: "lowConfidence", label: "Low-confidence segments", swatch: "coverage-swatch--low-confidence" },
  { key: "disputed", label: "Disputed evidence", swatch: "coverage-swatch--disputed" },
  { key: "labels", label: "Accessibility labels", swatch: "coverage-swatch--labels" },
];

export function CoverageControl({ visibility, onChange, onLoadForView, loading, disabledReason }: CoverageControlProps) {
  return (
    <section aria-labelledby="coverage-heading" className="coverage-control">
      <h2 id="coverage-heading">Coverage layers</h2>
      <p className="coverage-control__hint">
        Shows what evidence exists for the current map view. Supports the route comparison above; it isn't a separate
        analytics view.
      </p>
      <fieldset>
        <legend className="visually-hidden">Toggle coverage layers</legend>
        {OPTIONS.map((option) => (
          <label key={option.key} className="coverage-control__option">
            <input
              type="checkbox"
              checked={visibility[option.key]}
              onChange={(event) => onChange({ ...visibility, [option.key]: event.target.checked })}
            />
            <span className={`coverage-swatch ${option.swatch}`} aria-hidden="true" />
            {option.label}
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        onClick={onLoadForView}
        disabled={loading || disabledReason !== null}
        aria-busy={loading}
      >
        {loading ? "Loading coverage…" : "Load coverage for current map view"}
      </button>
      {loading && (
        <p role="status" className="coverage-control__hint">
          Loading coverage data for the current map view&hellip;
        </p>
      )}
      {!loading && disabledReason && (
        <p role="status" className="coverage-control__hint">
          {disabledReason}
        </p>
      )}
    </section>
  );
}
