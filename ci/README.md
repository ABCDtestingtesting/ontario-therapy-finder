# Live Mac verification using GitHub Actions

This adds actual macOS internet tests to the software. It is not a claim of 100% coverage. The four hosted machines are **macOS 15 Apple silicon (`macos-15`)**, **macOS 15 Intel (`macos-15-intel`)**, **macOS 26 Apple silicon (`macos-26`)**, and **macOS 26 Intel (`macos-26-intel`)**. Both run the checked-in application, not simulated replacement code.

Each machine runs the normal 64+ local tests and six independent live probes:

1. Real HTTP dashboard and API startup.
2. Actual `start.command` execution on the hosted Mac, including its Python environment, dependencies, and dashboard launch.
3. Real Statistics Canada downloads, FSA/DA boundaries, and a 5 km L7A population catchment.
4. Real pinned Google Maps collector installation and a small Hamilton search.
5. Real Firefox browser collection from the L7A Psychology Today directory; challenge/shortfall means **failure**.
6. Real Street View screenshot capture at sampled L7A residential dissemination areas. Image content must still be reviewed; a screenshot is not automatically a housing classification.

The workflow saves stage-specific logs, browser challenge screenshots and collection diagnostics. The final job fails if any of the six checks failed or never ran, regardless of earlier `continue-on-error` flags.

## Launch remotely

1. Put the **contents** of this folder in the top level of a GitHub repository, preserving the `.github/workflows/` directory. Use a public repository for free standard hosted runner time. Do not include client records, personal authentication or local exports. If a private repo is used, GitHub billing allowances apply.
2. Open the repository's **Actions** tab, select **Real macOS verification (live sources)**, choose **Run workflow**.
3. Open all four Apple silicon and Intel jobs. If any test fails, download the `mac-live-test-*` artifact on that job's run page. The `ci_results/*.log` files identify which source actually failed.

The workflows are configured to run on relevant source updates as well. They need no Google API key and no user login, though external sources may still block automated access. A failure is useful evidence and must be fixed rather than ignored.

This tests actual macOS computers, but it does not test every macOS version, user permissions, or desktop GUI on a user's personal Mac. The remote browser is unattended/headless; the user's local workflow uses a visible Firefox. Passing hosted tests is necessary evidence, not a universal guarantee.
