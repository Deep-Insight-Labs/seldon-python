---
name: seldon-operation
description: Compare and adopt one explicitly selected AI operation through Seldon Functions.
---

# Improve one selected operation

Use only the selected call and its immediate dependencies. Never upload the whole repository.
Preserve the existing framework, rendered instructions, output parser and omitted settings.
Capture a representative request at the actual adapter seam. Static inspection is not proof
of dynamic behavior. Ask only about consequential ambiguity; do not invent labels or criteria.

Prepare source.json and representative examples locally. Show exactly which files/fields would
be uploaded, to which Seldon host, and which checks remain unknown. Never include credentials.
Run `seldon import --source source.json --offline` before remote work. Source import does not
require a decorator or application-module import. With no CLI login, offer dashboard Import.

# After the user approves

Use `seldon login` for management; inference keys cannot manage Functions.
Run `seldon import --source source.json`, retaining the returned Function identity in the local
association. If creation has an unknown outcome, inspect `seldon status` and reconcile the
actual Function before retrying with `--function`; never infer identity from prompt/model.
Run `seldon examples import <function> --file examples.jsonl --replace` only after showing the
replacement scope. Missing expected-output provenance is unspecified, not human labelled.
Choose comparison first when the scoped readiness is unknown or insufficient. For an explicitly
chosen integrate-first journey, inspect `seldon reference-readiness <function>`; explain the
55-second deadline, workspace capacity and unknowns. `seldon serve-reference <function>` requires
the user's own login and interactive approval; `--acknowledge-deadline-risk` is an explicit
acknowledgement only after discussing the scoped risk. Reference serving is not optimization.
Later comparison uses the saved source run and its explicit additional cap.
Run `seldon optimize <function> --cap <authorized-total> --yes --wait` only within the explicit
cumulative budget. Preserve its run id, held/spent amounts and cancellation state. A timeout or
new agent session never authorizes another paid run. Use `seldon status <function>` and
`seldon report <function> --run <saved-run>` to resume. `--new-run` requires a new bounded scope.

Present measured tradeoffs, disagreements, missing evidence and a next action: adopt, retain
original or obtain better evidence. Inspection is optional. Generated explanation is not
semantic verification. Report-only targets never become activation vetoes. Never hide warnings.

Prepare a small patch for this operation plus necessary configuration/tests. Rehearse success,
a real boundary failure and recovery through the owning application's call site. Preserve its
production alias during rehearsal. `seldon publish <function> --revision <revision>` and
`seldon activate <function> --revision <revision>` require the human's interactive confirmation;
an agent must not simulate a terminal or bypass it. Distinguish publication, activation,
application testing and deployment. Show whether the patch pins a revision or follows the alias.

Offer `seldon function pull <function>`, `seldon function verify <function>` or
`seldon function run <function> --input inputs.json` only for an eligible, activated local revision. Explain
model installation, conformance, refresh, cloud-capable fallback and opt-out telemetry. Hosted
measurements do not prove local benefit. Local ineligibility never blocks hosted adoption.

Typed integration is optional: export the selected decorated module, import one generated source,
then write its Function id with `seldon lock set <key> <function> --module selected.module`. Explain canonical JSON rendering differences,
strict input/output validation and configured reference fallback. Existing-client integration
retains its framework and parser; both use the same evidence and approval flow.

Use `seldon check --source source.json` for offline drift. On return, read the saved association
then authoritative server state; changed source/evidence invalidates the recommendation.
Do not silently create another Function, rerun paid work, activate or deploy. Record exact
source/run/revision identifiers, tested boundaries and remaining gaps without secrets.
