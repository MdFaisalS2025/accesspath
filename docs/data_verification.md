# Data Verification — Week 1

## City boundary used

Both raw datasets are scoped to the **official Seattle administrative boundary**
(OSM relation `237385`), not an arbitrary bounding box:

- Boundary bbox (confirmed identical from both Nominatim and the OSM relation
  geometry itself): lat `47.4810022` to `47.7341503`, lon `-122.4596960` to `-122.2244330`.
- The boundary polygon was reconstructed from the relation's 54 member ways
  (688 vertices) via Overpass (`relation(237385); way(r); out geom;`) and
  polygonized with Shapely.

## OSM extract

Query: all `highway=footway`, `highway=path` (excluding `foot=no`),
`highway=pedestrian`, `highway=steps`, `footway=crossing` ways, plus
`kerb=*` and `highway=crossing` nodes, inside `area(3600237385)` (the same
relation as an Overpass area, i.e. exactly the polygon above, not a bbox).

Result (`data/raw/osm_seattle_pedestrian.json`, 226,229 elements):

| Element | Count |
|---|---|
| `way: footway` | 119,174 |
| `node: kerb=lowered` | 34,188 |
| `node: highway=crossing` | 46,053 |
| `node: kerb=raised` | 15,894 |
| `node: kerb=flush` | 3,359 |
| `way: steps` | 3,020 |
| `node: kerb=no` / `none` | 3,545 |
| `way: pedestrian` | 459 |
| `way: path` | 427 |
| `node: kerb=rolled` | 100 |

This is a materially richer graph than the earlier planning-stage estimate
(which only counted `sidewalk=*`/`kerb`-on-way tags) — Seattle has dense,
node-level kerb-ramp tagging in addition to dedicated sidewalk ways.

## Project Sidewalk labels

`data/raw/sidewalk_labels_seattle.json`: 262,053 labels pulled live from
`sidewalk-sea.cs.washington.edu`'s raw labels API (CC0 1.0, no bbox filter
applied — this is Project Sidewalk's full Seattle deployment export).

Each label already carries an `osm_way_id` and `street_edge_id` assigned by
Project Sidewalk itself at collection time. This means the segment join in
the pipeline (Section 9 of the planning doc) can primarily use this
**existing ID match** rather than relying only on nearest-geometry matching —
geometric matching is needed only as a fallback for labels whose
`osm_way_id` doesn't resolve to a way in our extract (e.g. the way was
deleted/edited in OSM since Project Sidewalk recorded it).

## Boundary cross-check: labels vs. city polygon

Every label point was tested against the actual Seattle polygon (not just
the bounding box) using Shapely's `contains`:

- **262,053 labels total**
- **246 labels (0.094%) fall outside the polygon**
- All 246 are in named Seattle neighborhoods right at the boundary edge
  (South Delridge 79, Highland Park 67, South Park 34, Roxhill 28,
  Pinehurst 9, Rainier Beach 7, Olympic Hills 6, Rainier View 5, Bitter
  Lake 4, Arbor Heights 3, plus a few more) — these are genuine Seattle
  neighborhoods per Project Sidewalk's own `region_name` field, so this is
  boundary-precision noise (the reconstructed polygon vs. the exact legal
  line), not a real city mismatch.

**Conclusion:** the two datasets are geographically consistent. The 246
edge-case labels will be **kept** (joined by `osm_way_id` if it resolves to
a segment in the graph, since the pedestrian OSM query above is not itself
strictly bbox/polygon-limited in a way that would exclude a way whose
label sits a few meters outside the admin line) and flagged in
`match_method` if no matching segment exists. They will be reported as
`unmatched` in the pipeline output, not silently dropped and not silently
counted as "no issue" for a nearby segment.

## Licensing note (see also planning doc Section 7)

- Project Sidewalk label **metadata** (coordinates, label type, severity,
  validation counts) is CC0 1.0 — no restriction on use or redistribution.
- Labels were originally collected by Project Sidewalk volunteers auditing
  Google Street View panoramas (`pano_source: "gsv"`, `pano_url` field
  present in the raw data). **We do not fetch, store, or display any GSV
  imagery** — only Project Sidewalk's own derived label data is used, which
  avoids Google's Street View redistribution restrictions entirely.
- OSM data remains ODbL — attribution required in the README/UI footer.
