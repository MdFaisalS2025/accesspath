// Shown only when GET /deployment-info reports mode "hosted_subset" (the
// free-tier demo deployment) -- never in local dev or a full-dataset
// deployment. Deliberately restrained (a single-line notice, not a modal
// or a red alert) per this task's "visible but restrained" requirement --
// this is a scope disclosure, not an error or a warning about a problem.
interface CoverageBannerProps {
  message: string;
}

export function CoverageBanner({ message }: CoverageBannerProps) {
  return (
    <div className="coverage-banner" role="note">
      <span aria-hidden="true">ⓘ</span>
      <p>{message}</p>
    </div>
  );
}
