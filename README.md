# Ontario Therapy Area Finder — version 5.1, clean Mac installation

## Start (Mac)

1. Extract the ZIP to your Desktop or Documents; do not run it from inside the ZIP.
2. Double-click **start.command**. It sets up its own Python environment and downloads Playwright Firefox. Before opening the dashboard, it runs all bundled local tests on your Mac. These are software checks, not proof that Google or Psychology Today will respond to searches. No Google Cloud or credit card required. Python dependencies and Playwright Firefox require internet access. If Python 3.11+ is missing, the launcher now attempts to install a user-local Python 3.12 automatically using uv without administrator privileges.
3. Wait for the local dashboard to open automatically. Keep its Terminal window open.
4. Click **Download and validate census data**. Its progress and errors appear beneath the button. The program downloads Statistics Canada 2021 FSA populations, DA populations, and official Ontario FSA boundaries.
5. Start with **L7A** and click **Run / resume all four sources**. This live pilot checks the external sources before you run hundreds of areas. The program first attempts visible Firefox Google Maps collection with resumable grid searches. If that cannot collect complete evidence, it tries the pinned free Google Maps engine and, if necessary, its Go-based source-build fallback. If an installation fails, the dashboard shows the error, saves logs, and preserves the unfinished job. This external binary has not been run live on your Mac.
6. Use **Inspect evidence** to examine the original Google results, Psychology Today records and housing photographs. If any Psychology Today profiles have an unknown local/online classification, open their linked original profiles and classify them in that panel. For housing, review at least six actual residential photos per FSA (or use the optional local vision model). Record the audit you performed. The final ranking refuses to treat unresolved searches as zero competitors. A directory listing with an L7A postal code is counted as a locally advertised listing, not automatically as an in-person practice.
7. When the pilot works, use **Show eligible areas**, **Select all listed**, **Run / resume**. Click **Check completeness and rank** after every selected area has passed the source reviews. The exports appear in `output/` and as download links on the dashboard.

The system is free and local, but the initial census tables and map scans involve substantial downloads and potentially long collection sessions. Google Maps and Psychology Today can change their pages or restrict access. An external site may require interactive verification. No software can guarantee all real therapy practices appear in those directories; the report is an observed-directory analysis.

## Revision 5.1 — verified regression fix

- Corrected Psychology Today to follow actual 1-based pagination: the initial URL is `/ca/therapists/l7a`, and the following page is `?page=2`, then `?page=3`, etc. An earlier collector expected `?page=1`, and could stop at page one. The current public directory links were independently checked in November 2026.
- Added simulated four-page continuation, page-gap detection, and interruption regression tests; the local package passes 64 automated tests.
- IMPORTANT: Public website navigation was verified with web retrieval, but real browser collection on the user's Mac, external Google Maps executable installation, automatic housing-photo classification, and the complete census download are still untested end-to-end. No 100% guarantee is possible from this environment. If a stage fails, consult `diagnose.command` without deleting its saved records.

## Project architecture

- `finder/census.py`: official 2021 StatCan CSV importer, validation, paginated ArcGIS FSA/DA geometry requests, approximate 5 km population catchments.
- `finder/maps.py`: adapter for [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper), pinned to `v1.19.0`, overlapping 1-km grid, 5.5-km margin around every FSA, original CSV, resume sidecar and audit.
- `finder/psychology_today.py`: visible Playwright Firefox, directory pagination, profile-level deduplication, saved HTML pages, summary counts, verification challenge and resume.
- `finder/housing.py`: populated DA street-level sampling, actual Google Street View screenshots, local Ollama classification or explicit human review.
- `finder/rank.py`: residential candidate points in populated census DAs, 2021 local population and mapped Google business locations inside 5 km, locally advertised Psychology Today postal listings per 10,000 FSA residents (not verified in-person clinicians), and verified housing types within 2 km. It ranks locations using a transparent average of the two *separate competition-rate indicators* and proposes up to two geographically separated candidates. The combined number is a screening index, not a therapist headcount. Local postal-code presence does not establish whether a clinician offers in-person sessions.
- `finder/server.py` + `web/index.html`: one local dashboard with a consistent JSON protocol, progress, errors, data review, local map and exports.
- `tests/`: unit and integration tests, including faulty-response tests, geospatial edge cases, incomplete source gates, screenshot rejection and actual browser clicks.

## Practical caveats

- Statistics Canada population is the 2021 baseline, not a verified 2026 estimate. DA catchments assume population evenly spread inside each DA polygon. Newer buildings can change the picture.
- Google business locations count mapped businesses and clinics, not therapist capacity or number of clinicians per clinic. Psychology Today profiles separately reflect directory visibility; a provider may appear in multiple area searches.
- A complete scraping job means the scheduled search finished and produced auditable evidence. It does not prove a commercial directory includes every existing practitioner. A grid collector may also miss listings when a site rate-limits or omits them: scrutinize its raw search grid and logs before approving.
- Google Maps counts individual mapped businesses or office locations. Psychology Today counts listed profiles, which can overlap with the mapped businesses; do not sum them as unique therapists. Their per-capita rates enter a transparent 50/50 screening indicator. The indicator is a decision aid, not a population-adjusted count of distinct clinicians.
- Candidate office points require a verified residential photograph within 2 km. Empty or inaccessible photographs are flagged for review and cannot support the final two recommendations.
- The bundled tests cover simulated search responses and the local interface. We cannot confirm live website automation on your Mac until the pilot run successfully processes live Google Maps, Psychology Today and census data. The program will flag failures rather than invent completed results.
- Street View sampling depends on panorama coverage and photographs. Screenshots need visual verification or a suitable local model with strong confidence. The model is optional; double-click `install_vision_optional.command` to install the free Ollama model if your Mac can accommodate it. No image-based estimate substitutes for population data.
- For long scans, leave Terminal open. The dashboard Stop button interrupts Google collection, PT page collection, or housing-photo capture, preserving evidence. If stopped, reopening `start.command` resumes from saved stage-level data. Some collectors also maintain their own resumable file output. To view the detailed cause of a failed task inspect `logs/last_error.log`. For a ready-to-share diagnostic report, double-click `diagnose.command`: it creates `output/diagnostics_*.zip` with version information and failures but omits full therapist profiles and photographs.
- The program refuses to export a final comparison if any selected area lacks a validated required source. The queue can still have unfinished areas; no missing results become zero.

## Audit and warranty limits

This package has passed local unit, HTTP, UI, simulated collector and interruption tests. **It has not passed a real-world end-to-end run on your specific Mac**. Its census downloads, first-time Google engine installation, live Psychology Today page parsing, street-photo navigation and optional Ollama model require real external connections and may change. No local test suite can establish that third-party search directories are exhaustive. Use the L7A pilot before launching the full area scan. The program must report incomplete sources instead of fabricating a ranking.

## Verified public references

- Statistics Canada FSA population table: https://www150.statcan.gc.ca/n1/tbl/csv/98100019-eng.zip
- Statistics Canada DA population table: https://www150.statcan.gc.ca/n1/tbl/csv/98100015-eng.zip
- Statistics Canada geometry layers FSA 14 and DA 12: https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer
- Google scraper public documentation: https://github.com/gosom/google-maps-scraper
- Psychology Today Ontario directory: https://www.psychologytoday.com/ca/therapists/ontario
- Google Street View URL schema: https://developers.google.com/maps/documentation/urls/get-started

## Subsequent live-testing corrections

- ArcGIS FSA and DA geometry queries now split server-failing batches without skipping any results, and FSA boundaries can fall back to an independently verified copy of the official 2021 shape archive.
- Google Maps searches use resumable Firefox first; the original native Go collector remains a backup. Search links without coordinates are reopened individually to retrieve coordinate-bearing place URLs.
- In visible Firefox, Google verification prompts remain open until completed or explicitly stopped. In headless CI, any challenge fails the test and saves a diagnostic screenshot.
- The Mac launcher now installs user-local Python when unavailable; executable modes are verified in the release pipeline.
- Release is withheld until live external source checks pass; local unit tests alone are insufficient.


## Source restrictions and browser-verification recovery

If Google Maps or Psychology Today presents a human-verification challenge during an interactive local scan, use the **existing Firefox tab** to complete it. The program keeps that session open while it waits for real search results; do not close Firefox or restart the scan. The dashboard's **Stop** control remains available if you cannot finish the challenge; reopening the application and selecting **Run / resume** retains its last completed pages or grid cells.

HTTP 429 (rate limiting) and unsolvable HTTP 403 access restrictions are reported as incomplete source stages. Wait before retrying. The program neither bypasses human-verification controls nor rotates identities to evade a provider's restrictions. A blocked Google Maps Firefox search does not trigger a competing scraper against the same blocked site, and subsequent areas in the same bulk run defer that source instead of repeatedly contacting it. Other independent sources may continue. The final ranking remains unavailable until source evidence is complete and reviewed; an unverified result is never a zero-competition claim.

GitHub Actions runs unattended: if a provider requires interactive verification, its stage correctly fails with saved diagnostics. A successful automated Mac test also cannot guarantee that a provider will never challenge the user's local browser or that its public listings cover every therapist.
