# Changelog

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
