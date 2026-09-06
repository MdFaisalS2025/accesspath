"""
Re-fetches the raw OSM + Project Sidewalk extracts used for AccessPath (Seattle).

This documents/reproduces the Week 1 data pull described in
docs/data_verification.md. It does not transform or load the data —
see build_graph.py (added in Week 2) for that.
"""
import json
import urllib.request

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SEATTLE_RELATION_ID = 237385
SEATTLE_AREA_ID = 3600000000 + SEATTLE_RELATION_ID

OSM_QUERY = f"""
[out:json][timeout:180];
area({SEATTLE_AREA_ID})->.seattle;
(
  way["highway"="footway"](area.seattle);
  way["highway"="path"]["foot"!="no"](area.seattle);
  way["highway"="pedestrian"](area.seattle);
  way["highway"="steps"](area.seattle);
  way["footway"="crossing"](area.seattle);
  node["kerb"](area.seattle);
  node["highway"="crossing"](area.seattle);
);
out body geom;
"""

PS_LABELS_URL = (
    "https://sidewalk-sea.cs.washington.edu/v3/api/rawLabels"
    "?filetype=geojson&inline=true"
)


def fetch_osm(out_path: str) -> None:
    data = urllib.parse.urlencode({"data": OSM_QUERY}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data)
    with urllib.request.urlopen(req) as resp, open(out_path, "wb") as f:
        f.write(resp.read())


def fetch_project_sidewalk_labels(out_path: str) -> None:
    with urllib.request.urlopen(PS_LABELS_URL) as resp, open(out_path, "wb") as f:
        f.write(resp.read())


if __name__ == "__main__":
    import urllib.parse

    fetch_osm("data/raw/osm_seattle_pedestrian.json")
    fetch_project_sidewalk_labels("data/raw/sidewalk_labels_seattle.json")
    print("Done. See docs/data_verification.md for expected counts.")
