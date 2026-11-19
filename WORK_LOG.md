# Functions adoption SDK implementation work log

## 2026-11-19 — separate local repository

Created this Apache-2.0 local repository on `feat/functions-adoption` as the shared
SDK/CLI owner. No remote repository, package registry publication, deployment or
paid provider request was performed. Public fixtures and instructions were written
for this repository; private Vector prompts and source code are not included.

Implemented the selected-operation CLI, optional typed runtime, local Runner
adapter and narrow packaged skill. Full SDK delivery remains a development preview:
release/production activation and the external acceptance below are independent.

### Evidence

- Core unit suite: 37 passing tests at this checkpoint. HTTP responses are replaced
  at httpx MockTransport; credential storage uses Login's store interface; typed
  local tests replace Runner.load. All actual async calls are awaited.
- Pydantic minimum: twenty synthetic schema shapes compared against 2.14.3.
  Every minor 2.0 through 2.10 failed digest equality; 2.11.0 passed. Python 3.11
  with 2.11.0 passed the then-current 34-test suite. Python 3.10.19/2.11.0 and
  Python 3.13.15/latest passed the installed-wheel 34-test suite. Later final
  verification is appended below, rather than retroactively expanding those claims.
- Cross-repo canonical fixtures: thirty SDK-owned synthetic cases were evaluated by
  Seldon's actual `sdk_contract.import_sdk` and `executor.render_request` exporter.
  SDK-generated sources/digests/rendered messages agree with that corpus. The
  owning server regeneration test passes. Includes repeated parameters across
  messages, escaped JSON, Unicode, dates, null, booleans, numbers and containers.
- Fresh wheel: `python -m build` produced sdist+wheel; `scripts/verify_wheel.py`
  installed that wheel in a new venv, exercised the console shim, offline import
  and typed stub from an unrelated directory. Lazy package import loads neither
  server/runtime, httpx nor Pydantic and completed below the 150ms bound for that
  process. This is a smoke observation, not a multi-process p95 benchmark.
- Public sync/async annotations pass `mypy --strict scripts/typecheck_example.py`.
  This is consumer typing evidence, not a claim that all internal implementation
  functions have strict annotations.
- Seldon integration test `tests/sdk_compat/test_functions_cli_artifact.py`: fresh
  installed Python 3.13 CLI subprocesses → real uvicorn HTTP → migrated Postgres
  on port5499 → Redis6499 → durable worker/provider fixture. Passed registration,
  idempotent sync, pending drift check, explicit paid-run consent, authoritative
  run reconciliation, report, publication/pinned serve, activation, success,
  authentication failure/recovery, saved-run resume and cleanup. One observed run
  passed in 41.18s. WorkOS issuance is replaced by the existing development
  service-JWT seam; actual role/lifecycle/API-key checks remain active.
- The separate private Vector worktree preserves its existing PydanticAI parser.
  Its adapter/worker tests passed20; the Seldon cross-repo actual application
  subprocess → published pinned Function/runtime test passed7.00s with a shared
  measured-revision factory and deterministic provider. No public SDK test or
  fixture contains its prompts. Those results prove application wiring, not
  financial-document correctness or savings.
- Ruff lint/format and the packaged skill's structural validator are checked before
  commit. Skill-creator guidance was used to keep scope and approvals explicit.

### Contracts and degradation

| Dependency | Interface and seam | Failure behavior |
| --- | --- | --- |
| Seldon management | sync httpx; injected Login/http | bounded error, no automatic mutation retry; uncertain create requires explicit reconciliation |
| WorkOS device/refresh | sync httpx, store/sleep/clock seams | bounded polling; no API-key fallback; rotate refresh token before downstream verification |
| OS credentials | sync keyring allowlisted backend or injected store | memory-only when unavailable at discovery, explicit error when configured storage fails |
| Function/reference execution | sync thread client or async loop client; injected client | bounded retry; explicit fallback matrix; auth/funding/input errors never fall back |
| Local Runner | async public load/call/status/aclose | runtime owns eligibility/conformance/refresh; no unverified typed execution |

Source and evidence files stay local until an explicit import. Local associations
hold identifiers/digests/paths only. Auth profiles bind credentials to profile+HTTPS
origin; no redirects carry them to another host. Report reads pin the run id when
associated. Unknown provider capacity and missing local verification are never
reported as successful evidence.

### Remaining external qualification and known scope limits

Live issued-token WorkOS login/refresh/revocation is not established by mocked HTTP
or the development JWT seam. Browser logout reports pending/unavailable rather than
claiming remote revocation. Public repository/name ownership, registry publication,
trusted-publisher configuration, release attestation and production flags are not
changed. Linux/Windows secure keychains and CPU model install/runtime behavior need
their own platform evidence. Real local weights were exercised by the runtime owner,
not by this SDK's unit local adapter test. Full local app fallback/refresh telemetry
qualification remains runtime-owned.

The scanner is intentionally conservative and offers migration guidance; it does
not emit an automatically valid decorator for arbitrary code or infer volume.
Full framework/version matrices, performance p95 suites, concurrent circuit stress,
real-network device-login outcomes and extended/nightly readiness are not claimed
from the focused checks. Existing-client offline validation preserves raw envelopes
and performs bounded structural checks; server contracts remain authoritative for
complete provider/evaluator eligibility.

### Final verification additions

The installed-wheel Python 3.10.19/Pydantic2.11.0 and
Python3.13.15/Pydantic2.14.3 suites both passed37 tests after conformance and public
typing additions. The clean fresh-environment artifact smoke passed again.
Subsequent explicit managed-fallback approval coverage brings the local suite to38;
both publish and activation forward that flag only after interactive confirmation.
The server integration run including source-first reference-readiness/serve-reference
and conformance regeneration passed2 tests in40.47s. Thus both journey orderings
have an actual route/installed-CLI boundary rehearsal. Production feature flags
remain untouched. The Vector application worktree commits are `fe2b77ee` and
`7b533349`; its local main remains unchanged.

Final wheel rebuilt after the approval and bounded-file-read changes: both fresh
installed environments (Python3.10.19/Pydantic2.11.0 and
Python3.13.15/Pydantic2.14.3) pass all38 tests. Local Ruff and public strict typing
checks pass. No editable SDK installation is used by those two artifact suites.

## 2026-11-19 — final preparation/report hardening

The AC audit found that command key locators did not consult the shared lockfile.
They now resolve the nearest/SELDON_LOCKFILE mapping without module imports and
reject malformed self-references without recursion. Reports preserve selected run,
contract digest, diagnostics and serving state; source import returns the actual
server digest and reuses unchanged identity. Offline preview includes destination.
Three added regression tests bring the suite to41 passing. Public strict consumer
typing, Ruff/format, build, twine and fresh Python3.10 base-wheel console/offline/
typed-stub checks pass. Artifact assertions now check license files and prohibit
fixture/test payload in the wheel. CI runs those packaging checks.

The Seldon QA work log lists remaining compound ACs explicitly: public publication,
issued WorkOS login/logout, complete invalid corpus/provenance, internal strict
typing and exhaustive performance/retry/concurrency/scanner matrices. Human-timed
baseline and provider quality/savings remain unmeasured. Actual owning-application
local Runner success/fallback/raise is not covered by the hosted Vector rehearsal.

The final plan audit also implemented lockfile-wide `status` (per-key active,
pending or stale digest plus read-only usage) and 1-based `activate --alternative`
selection from the associated server report. Both retain explicit-ID support,
interactive owner confirmation and server role checks. Two regressions bring the
suite to43 passing, including zero requests for noninteractive alternative
activation. These are implemented command paths, not deferred conveniences.
