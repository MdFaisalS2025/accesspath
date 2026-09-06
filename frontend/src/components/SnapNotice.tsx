import { EndpointInfo } from "../api/types";

interface SnapNoticeProps {
  label: string;
  endpoint: EndpointInfo;
}

// Week 6 requirement: the same-component snapping substitution must be
// disclosed clearly when used, including the snap distance and the fact
// that the chosen node differed from the unconstrained nearest node --
// never silent, per app.core.geo's own contract on the backend.
export function SnapNotice({ label, endpoint }: SnapNoticeProps) {
  const { snap } = endpoint;
  return (
    <p className="snap-notice">
      <strong>{label}</strong> snapped to the nearest routable point,{" "}
      {snap.snap_distance_m < 1 ? "less than 1 m" : `${Math.round(snap.snap_distance_m)} m`} away.
      {snap.adjusted_for_connectivity && (
        <>
          {" "}
          A closer point existed ({Math.round(snap.nearest_unconstrained_distance_m)} m away) but was not part of the
          same connected network as the other endpoint, so this slightly farther point was used instead to make a
          route possible.
        </>
      )}
    </p>
  );
}
