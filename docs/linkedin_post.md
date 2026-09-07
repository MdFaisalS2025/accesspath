What should a route planner do when it has no accessibility data for a street?

Most systems quietly treat “unknown” as “probably fine.” I built **AccessPath** to challenge that assumption.

AccessPath compares shortest, accessibility-optimized, and confidence-aware walking routes across Seattle using 213K OpenStreetMap pedestrian segments and 262K Project Sidewalk reports.

The most valuable moment was when my first scoring model failed. Ten positive curb-ramp reports could outvote one reliable report that there was no sidewalk. The math worked; the design didn’t. I replaced it with a dominance-aware model that prevents severe, credible hazards from being averaged away.

I used AI openly throughout the project: **Claude Code** helped implement and test the system, while **OpenAI Codex** acted as a second reviewer—challenging assumptions, checking reports, and shaping the evaluation prompts. I made the product decisions, reviewed the evidence, and required every important claim to be backed by tests or measured results.

The stack: Python, FastAPI, PostGIS, NetworkX/A*, React, TypeScript, MapLibre, Docker, Vercel, Render, and Neon.

The evaluation was intentionally honest. In eight curated examples, confidence-aware routing reduced completely unknown-segment exposure whenever an alternative existed—but sometimes replaced it with low-confidence evidence. This is a research prototype, not a safety-certified navigation tool.

Next, I’d like to work with wheelchair users and accessibility researchers, expand the evaluation, add slope and construction data, and test whether the scoring choices reflect real experiences.

Try it: https://accesspath-silk.vercel.app/
Code and engineering report: https://github.com/MdFaisalS2025/accesspath

#Accessibility #Geospatial #SoftwareEngineering #ResponsibleAI #BuildInPublic
