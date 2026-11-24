PT Weekly Index Survey — Mac
Double-click Run.command. No signup, API key, credit card, or browser automation. Python 3.9+ with Toronto timezone data required. The launcher checks its actual collector before starting. Run.command --self-test runs tests without network calls.

Reports: ~/Library/Application Support/PT Weekly Index Survey/<Monday date>/
weekly-index-visibility.csv contains all 60 candidate FSAs, candidate directory links, indexed leads and leads with matching postal text. These links follow the Canadian PT URL pattern; their current page contents and listing-area eligibility are not verified. Indexed leads are not current PT competitor counts. No exact ranking is asserted. coverage.json gives source coverage and blockers; daily JSON records timestamps and result hashes. A rerun on the same date resumes successful queries, retries failed queries, and does not count unavailable sources as zero. Run on different days for weekly comparisons. Transient network errors retry with bounded backoff; rate limits and access denials stop that source for the run. Exit 3 means incomplete collection. Even exit 0 means only index coverage, never confirmed PT competition.

No direct automated PT access is enabled. For exact membership/counts, obtain authoritative counts or permission for directory verification. No legacy API-key configuration is needed.
