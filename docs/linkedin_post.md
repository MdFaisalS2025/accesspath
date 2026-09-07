I just shipped AccessPath — a routing prototype that treats "we don't know" and "we checked and it's fine" as genuinely different things.

Most accessibility-routing demos quietly assume every unlabeled street is walkable. The problem: most of Seattle's sidewalks have zero crowdsourced accessibility data. So the real engineering question wasn't "how do I draw a route on a map" — it was "how do I stop the system from lying by omission."

AccessPath compares three walking routes side by side — shortest, accessibility-optimized, and confidence-aware — over 213K OpenStreetMap segments and 262K real Project Sidewalk accessibility reports.

The part I'm most proud of: the scoring model. My first version used a straightforward weighted average, and it broke immediately under adversarial testing — ten positive "curb ramp present" reports could mathematically outvote one reliable "no sidewalk here at all" report. So I rebuilt it as ceiling-capped risk accumulation: a segment's score is capped by its worst *reliable* hazard report, and no volume of unrelated positive evidence can lift that ceiling back up.

Then I evaluated it honestly. I froze 8 benchmark routes before looking at a single result, specifically so I couldn't unconsciously cherry-pick a flattering example afterward. The results are genuinely mixed: confidence-aware routing does cut how much of a route passes through totally undocumented segments — but it does that by routing onto *more* low-confidence segments in over half the cases where it had a real choice. I wrote that trade-off into the report directly instead of only showing the metric that looks good.

Full stack, solo build: PostGIS spatial pipeline → FastAPI + A*-optimized routing → React/MapLibre frontend, deployed on Vercel + Render + Neon (with a real 512MB memory budget I measured, not guessed). 96 backend tests, 29 frontend tests, WCAG AA accessibility pass, and a written evaluation that says "here's where this doesn't work" as clearly as "here's where it does.

Live demo (a curated coverage area, clearly disclosed as such — full Seattle data runs locally): https://accesspath-silk.vercel.app
Code + full engineering writeup: https://github.com/MdFaisalS2025/accesspath

Not a safety tool. Not a finished product. A demonstration that "confidence-aware" can mean something concrete and testable, not just a feature name.

#accessibility #softwareengineering #geospatial #fastapi #react #buildinpublic
