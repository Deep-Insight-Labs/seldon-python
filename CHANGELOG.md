# Changelog

## 0.1.0.dev1 — Complete SDK evidence and runtime contracts (prepared)

- Fix pre-run evidence import failing for SDK-owned Functions: use the server
  evaluation-only update, preserving declaration identity and the active alias.
- Accept exported SDK sources and evaluation definitions without changing defaults
  or behavior digests.
- Preserve safe error locations/execution IDs and call the metadata hook exactly
  once, including input/configuration failures, local execution and stubs.
- Complete strict source typing and CI checks, lockfile schema/timestamps, public
  conformance provenance and invalid vectors. Add retry/concurrency/privacy and
  installed-artifact regression coverage. Publication remains pending.
- Server-first dependency: deploy the matching Seldon server with SDK evaluation
  registration and `PATCH /v1/seldon/functions/{id}/draft-evaluation` before
  publishing or using this preview. The earlier `0.1.0.dev0` remains published.

## 0.1.0.dev0 — local preview

- Add one shared CLI for explicit offline sources, WorkOS user sessions, durable
  operation associations, bounded optimization and historical report inspection.
- Keep unknown create outcomes unretried; preserve command IDs across uncertain
  prepare/evidence responses. Preserve rotated refresh tokens when the downstream
  API is temporarily unavailable.
- Add optional typed contracts, reference fallback, isolated stubs, export/lock/sync,
  digest-only drift inspection and AST discovery.
- Package the selected-operation skill and a thin local Runner integration. Reuse
  the existing runtime for eligibility, conformance, active refresh and telemetry;
  this package contains no compiler or model executor.
- Use argparse, httpx and Pydantic instead of adding a parallel CLI/auth/agent
  framework. Structured output uses the constant schema name `output` so renaming
  a function cannot alter its behavior digest.

- Resolve Function keys from the nearest explicit lockfile for every targeted CLI
  command, rejecting malformed recursive mappings. Preserve authoritative selected
  contract/run diagnostics in reports and source-import results. Offline source
  previews identify the upload destination. Verify license and contents on built
  wheel/sdist artifacts.
