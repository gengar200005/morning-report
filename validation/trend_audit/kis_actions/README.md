# V1 KIS corporate action metadata availability probe

Version2 extends the original twenty fixed GET identities with46 missing metadata requests derived from unresolved stock dividends and bonus issues. The first20 identities remain unchanged and new identities are sorted after them. The66-request plan contains14 split requests,17 dividend requests and35 bonus-issue requests. Each request is one ticker and one calendar year. No order endpoints, response-driven URLs, pagination, share-ratio inference or entitlement approval.

Authentication is reused from the immutable sibling `../kis_v1/collect.py`, SHA256 `30c130cee54517fc67b73a3a4600b6b685780bec213ee523b5e67b9011b13a59`. The local sibling copy supports tests only; **do not include it in the remote change set**.

Run offline tests: `python -B -m unittest discover -s validation/trend_audit/kis_actions -v`.

Live execution is restricted by the workflow's repository and branch guards. It uses one in-memory token, at least0.3seconds before each GET, at most two transient retries, and stops remaining requests on authentication/permission errors. Each attempt preserves redacted body and only response header `tr_cont`. Checkpoints use atomic JSON writes with SHA256 sidecars and immutable request identity matching. Interrupted JSON/sidecar pairs fail closed. Artifact retention is seven days, upload runs even after failure.

`tr_cont=M` or `F` is recorded as incomplete; it does not trigger unreviewed pagination. Other nonempty flags outside `D/E` are labelled `unrecognized_continuation_state` and retained for review. Empty successful responses are coverage gaps, not evidence of no corporate event. `coverage_complete` and `data_ready` remain false for every flag, including `D/E`, and even when metadata rows return. No face values are converted into actual share ratios; particularly complex001230 is left as source metadata. Returned field meanings, dates, tickers and full terms require subsequent review.

Missing `output1` is a malformed schema rather than an empty result. The CLI exits2 for blocked requests or HTTP/application/schema errors; valid empty responses and incomplete continuation remain protocol success with unresolved coverage. Reuse verifies checkpoint SHA, every referenced raw attempt SHA and request identity, and recomputes the final response classification. Orphan raw attempts or sidecars are preserved and fail closed; choose a clean output directory. The manifest records both `plan_canonical_sha256` and the workflow-pinned `plan_file_sha256`.

Official API source directories:

- https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/ksdinfo_rev_split
- https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/ksdinfo_dividend
- https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/ksdinfo_bonus_issue

The workflow triggers only on pushes changing its own path or `validation/trend_audit/kis_actions/**` on `validation/v1-kis-sample-20261104`. It tests before exposing credentials and requests repository Contents read and Actions read permission. This overlay is prepared for review; no push was performed by this task.

Version2 recovery uses `run_options.json` with the reviewed source run41789248223 (or null for no recovery). The workflow also has Actions read permission to download exactly `v1-kis-actions-41789248223-1` into a fresh output directory. It preserves the old execution metadata as `source_workflow_run_41789248223.json` before recording the new run. The collector intentionally accepts plan extensions within1–100 unique identities: each restored checkpoint is verified against its individual request identity and every raw SHA, so the original20 calls are reused and only46 new requests authenticate/read. Existing raw acquisition timestamps and bytes remain unchanged; reuse is marked in the new manifest and old evidence is not relabelled as newly acquired. A focused offline test seeds20 checkpoints, extends to66, and proves exactly46 GETs and one authentication in the second run.
