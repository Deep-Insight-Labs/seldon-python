"""Explicit management operations with durable request identities and no mutation retries."""

import math
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .errors import SeldonAuthError, SeldonContractError, SeldonError, SeldonSpendError
from .files import Association, digest, read_json, resolve_function, safe_code, validate_source

FUNCTIONS = "/v1/seldon/functions"


class Management:
    def __init__(self, login, *, association=".seldon/operation.json", http=None):
        self.login = login
        self.origin = login.origin
        self.http = http or login.http
        self.association = Association(association)

    def request(self, method, path, body=None, *, params=None):
        try:
            response = self.http.request(
                method,
                self.origin + path,
                json=body,
                params=params,
                headers={"Authorization": "Bearer " + self.login.access_token()},
                timeout=30,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise SeldonError(
                "request_outcome_unknown" if method != "GET" else "service_unavailable"
            ) from None
        try:
            data = response.json() if response.content else {}
        except ValueError:
            raise SeldonError("invalid_service_response", status=response.status_code) from None
        if response.status_code >= 300:
            envelope = data.get("detail", data) if isinstance(data, dict) else {}
            envelope = envelope if isinstance(envelope, dict) else {}
            code = safe_code(envelope.get("error"))
            error = (
                SeldonAuthError
                if response.status_code in (401, 403)
                else SeldonSpendError
                if response.status_code == 402
                else SeldonError
            )
            raise error(code, status=response.status_code)
        if not isinstance(data, dict):
            raise SeldonError("invalid_service_response")
        return data

    def detail(self, function, *, run_id=None):
        function = resolve_function(function)
        params = {"run_id": str(UUID(run_id))} if run_id else None
        detail = self.request("GET", FUNCTIONS + "/" + function, params=params)
        state = self.association.read()
        if state.get("function_id") == function:
            if state.get("base_url") not in (None, self.origin):
                raise SeldonAuthError("association_host_mismatch")
            if state.get("workspace_id") not in (None, str(detail.get("workspace_id"))):
                raise SeldonAuthError("association_workspace_mismatch")
        return detail

    def import_source(self, path, *, function=None, name="Selected operation", offline=False):
        source = validate_source(read_json(path))
        source_digest = digest(source)
        state = self.association.read()
        preview = {
            "source_file": str(path),
            "fields": sorted(source) if isinstance(source, dict) else ["calls"],
            "source_digest": source_digest,
            "destination": self.origin + FUNCTIONS,
        }
        if offline:
            return {
                **preview,
                "status": "validated_offline",
                "next_action": "dashboard_import_or_login",
            }
        try:
            self.login.access_token()
        except SeldonAuthError as exc:
            if exc.code == "login_required":
                return {
                    **preview,
                    "status": "validated_offline",
                    "next_action": "dashboard_import_or_login",
                }
            raise
        if state.get("pending_create") and not function:
            raise SeldonContractError("uncertain_create_reconcile_function_list")
        body = {"name": name, "source": source}
        if function:
            function = resolve_function(function)
            detail = self.detail(function)
            if state.get("function_id") == function and state.get("source_digest") == source_digest:
                if state.get("revision") == detail.get("revision"):
                    return {
                        **preview,
                        "function_id": function,
                        "status": "unchanged",
                        "contract_digest": detail.get("selected_contract_digest"),
                    }
            body["expected_revision"] = detail["revision"]
            result = self.request("PATCH", FUNCTIONS + "/" + function, body)
        else:
            self.association.update(
                source_file=str(Path(path).resolve()),
                source_digest=source_digest,
                pending_create=True,
                base_url=self.origin,
            )
            try:
                result = self.request("POST", FUNCTIONS, body)
            except SeldonError as exc:
                if exc.status is not None and 400 <= exc.status < 500:
                    self.association.update(pending_create=False)
                raise
        identity = resolve_function(str(result["id"]))
        self.association.save(
            {
                "source_file": str(Path(path).resolve()),
                "source_digest": source_digest,
                "function_id": identity,
                "workspace_id": str(result["workspace_id"]),
                "revision": result["revision"],
                "pending_create": False,
                "base_url": self.origin,
            }
        )
        return {
            **preview,
            "function_id": identity,
            "revision": result["revision"],
            "status": "imported",
            "contract_digest": result.get("selected_contract_digest"),
            "preview_issues": [
                {"code": safe_code(item.get("code"))} for item in result.get("preview_issues", [])
            ],
        }

    def _state(self, function):
        state = self.association.read()
        if state.get("function_id") == function:
            path = state.get("source_file")
            if path:
                self.association.require_source(digest(validate_source(read_json(path))))
            if state.get("evidence_file"):
                from .files import read_examples

                if digest(read_examples(state["evidence_file"])) != state.get("evidence_digest"):
                    raise SeldonContractError("evidence_changed_import_required")
        return state

    def status(self, function=None):
        if function is None:
            from .lockfile import locate, read

            path = locate(None)
            if path.exists():
                rows = []
                for key, entry in sorted(read(path)["functions"].items()):
                    row = self.status(entry["function_id"])
                    detail = self.detail(entry["function_id"])
                    active = next(
                        (
                            item
                            for item in detail.get("revisions", [])
                            if str(item["id"]) == str(detail.get("active_revision"))
                        ),
                        None,
                    )
                    row["key"] = key
                    row["local_state"] = (
                        "pending"
                        if active is None
                        else "active"
                        if active.get("source_digest") == entry["contract_digest"]
                        else "stale_lock"
                    )
                    rows.append(row)
                return {"items": rows}
            return {
                "items": [
                    self._summary(item) for item in self.request("GET", FUNCTIONS).get("items", [])
                ]
            }
        function = resolve_function(function)
        detail = self.detail(function)
        result = self._summary(detail)
        result["usage"] = self.request("GET", f"{FUNCTIONS}/{function}/usage", params={"days": 7})
        state = self.association.read()
        if state.get("function_id") == function:
            result["associated_run_id"] = state.get("run_id")
            result["local_state"] = (
                "registered" if state.get("revision") == detail["revision"] else "stale_lock"
            )
        return result

    @staticmethod
    def _summary(detail):
        return {
            key: detail.get(key)
            for key in (
                "id",
                "revision",
                "active_revision",
                "status",
                "disabled",
                "requests_7d",
                "serving_state",
            )
        }

    def report(self, function, *, run_id=None):
        function = resolve_function(function)
        state = self.association.read()
        if run_id is None and state.get("function_id") == function:
            run_id = state.get("run_id")
        detail = self.detail(function, run_id=run_id)
        return {
            "function_id": detail["id"],
            "workspace_id": detail["workspace_id"],
            "revision": detail["revision"],
            "run_id": run_id,
            "alternatives": detail.get("alternatives", []),
            "selected_run_id": detail.get("selected_run_id"),
            "selected_contract_digest": detail.get("selected_contract_digest"),
            "diagnostics": detail.get("diagnostics", {}),
            "serving_state": detail.get("serving_state"),
            "runs": [
                run for run in detail.get("runs", []) if run_id is None or str(run["id"]) == run_id
            ],
            "inspection_url": self.origin
            + FUNCTIONS
            + "/"
            + function
            + ("?run_id=" + run_id if run_id else ""),
        }

    def optimize(
        self,
        function,
        *,
        cap,
        objective="cost",
        max_p95_ms=None,
        authorize=False,
        wait=False,
        timeout=600,
        new_run=False,
        source_run=None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        function = resolve_function(function)
        try:
            budget = Decimal(str(cap))
            if not budget.is_finite() or not 0 < budget <= 100:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise SeldonContractError("invalid_cap") from None
        if not math.isfinite(timeout) or timeout < 0:
            raise SeldonContractError("invalid_timeout")
        detail = self.detail(function)
        state = self._state(function)
        run_id = (
            state.get("run_id") if state.get("function_id") == function and not new_run else None
        )
        run = next((run for run in detail.get("runs", []) if str(run["id"]) == run_id), None)
        if run_id and run is None:
            raise SeldonContractError("associated_run_unavailable")
        summary = {
            "function_id": function,
            "authorized_cap_usd": str(budget),
            "run_id": run_id,
            "quote": run.get("quote") if run else None,
        }
        if not authorize:
            return {**summary, "status": "confirmation_required"}, 3
        if run and Decimal(str(run["cap"])) != budget:
            raise SeldonSpendError("run_cap_changed_requires_new_run")
        if run is None:
            command = (
                state.get("command_id")
                if not new_run and state.get("function_id") == function
                else None
            )
            if not command:
                command = str(uuid4())
            self.association.update(
                function_id=function,
                workspace_id=str(detail["workspace_id"]),
                base_url=self.origin,
                command_id=command,
                cap_usd=str(budget),
                run_id=None,
            )
            policy = {"objective": objective}
            if max_p95_ms is not None:
                if not math.isfinite(max_p95_ms) or max_p95_ms <= 0:
                    raise SeldonContractError("invalid_latency_target")
                policy["max_p95_ms"] = max_p95_ms
            detail = self.request(
                "POST",
                f"{FUNCTIONS}/{function}/runs",
                {
                    "command_id": command,
                    "expected_revision": detail["revision"],
                    "cap_usd": str(budget),
                    "policy": policy,
                    **({"source_run_id": str(UUID(source_run))} if source_run else {}),
                },
            )
            runs = detail.get("runs", [])
            if not runs:
                raise SeldonError("run_identity_unavailable")
            run = next((item for item in runs if str(item.get("command_id")) == command), None)
            if run is None:
                raise SeldonError("run_identity_unavailable")
            run_id = str(run["id"])
            self.association.update(run_id=run_id, revision=detail["revision"])
        deadline = clock() + timeout
        submitted = False
        while True:
            if run["state"] == "awaiting_review":
                quote_id = (run.get("quote") or {}).get("id")
                if not quote_id:
                    raise SeldonError("quote_unavailable")
                detail = self.request(
                    "POST",
                    f"{FUNCTIONS}/{function}/runs/{run_id}/optimize",
                    {"quote_id": quote_id, "expected_revision": detail["revision"]},
                )
                submitted = True
                run = next(item for item in detail["runs"] if str(item["id"]) == run_id)
            result = {
                "function_id": function,
                "run_id": run_id,
                "state": run["state"],
                "outcome": run.get("outcome"),
                "spent": run.get("spent"),
                "held": run.get("held"),
                "cap": run.get("cap"),
                "optimize_submitted": submitted,
            }
            if (
                run.get("ended_at")
                or run["state"] in {"completed", "failed", "cancelled"}
                or not wait
            ):
                return result, 0
            if clock() >= deadline:
                return {**result, "status": "wait_timeout", "next_action": "resume_same_run"}, 4
            sleep(min(2, max(0, deadline - clock())))
            detail = self.detail(function, run_id=run_id)
            run = next((item for item in detail["runs"] if str(item["id"]) == run_id), None)
            if run is None:
                raise SeldonError("associated_run_unavailable")

    def cancel(self, function, run_id):
        return self._summary(
            self.request(
                "POST", f"{FUNCTIONS}/{resolve_function(function)}/runs/{UUID(run_id)}/cancel"
            )
        )

    def activate(
        self,
        function,
        revision,
        *,
        publish=False,
        alternative=None,
        confirm,
        interactive,
        managed_fallback_approved=False,
    ):
        if not interactive:
            raise SeldonAuthError("interactive_owner_confirmation_required")
        self.login.access_token()
        function = resolve_function(function)
        state = self.association.read()
        selected_run = state.get("run_id") if state.get("function_id") == function else None
        detail = self.detail(function, run_id=selected_run)
        if alternative is not None:
            choices = detail.get("alternatives", [])
            if revision is not None or not 1 <= alternative <= len(choices):
                raise SeldonContractError("alternative_unavailable")
            revision = choices[alternative - 1].get("revision_id")
            if revision is None:
                raise SeldonContractError("alternative_not_deployable")
        revision = str(UUID(revision))
        selected = next(
            (item for item in detail.get("revisions", []) if str(item["id"]) == revision), None
        )
        if selected is None:
            raise SeldonContractError("revision_unavailable")
        warnings = selected.get("metrics", {}).get("report", {}).get("warnings", [])
        summary = {
            "function_id": function,
            "revision_id": revision,
            "metrics": selected.get("metrics", {}),
            "warnings": warnings,
            "action": "publish" if publish else "activate",
            "managed_fallback_approved": managed_fallback_approved,
        }
        if not confirm(summary):
            return {"status": "confirmation_required"}, 3
        if publish:
            result = self.request(
                "POST",
                f"{FUNCTIONS}/{function}/revisions/{revision}/publish",
                {"managed_fallback_approved": managed_fallback_approved},
            )
        else:
            result = self.request(
                "POST",
                f"{FUNCTIONS}/{function}/activate",
                {
                    "revision_id": revision,
                    "expected_active_revision": detail.get("active_revision"),
                    "managed_fallback_approved": managed_fallback_approved,
                },
            )
        self.association.update(revision_id=revision)
        return self._summary(result), 0

    def serve_reference(self, function, *, acknowledge_deadline_risk=False, confirm, interactive):
        if not interactive:
            raise SeldonAuthError("interactive_owner_confirmation_required")
        identity = resolve_function(function)
        detail = self.detail(identity)
        readiness = self.request("GET", f"{FUNCTIONS}/{identity}/reference-readiness")
        if not confirm(
            {
                "action": "serve_reference",
                "function_id": identity,
                "readiness": readiness,
                "inference_billed": True,
                "acknowledge_deadline_risk": acknowledge_deadline_risk,
            }
        ):
            return {"status": "confirmation_required"}, 3
        result = self.request(
            "POST",
            f"{FUNCTIONS}/{identity}/serve-reference",
            {
                "expected_revision": detail["revision"],
                "expected_active_revision": detail.get("active_revision"),
                "acknowledge_deadline_risk": acknowledge_deadline_risk,
            },
        )
        current = self.detail(identity)
        self.association.update(
            function_id=identity,
            revision_id=result["revision_id"],
            run_id=result["run_id"],
            revision=current["revision"],
            workspace_id=str(current["workspace_id"]),
            base_url=self.origin,
        )
        return {**result, "function": self._summary(current)}, 0

    def import_examples(self, function, path, *, replace=False):
        from .files import read_examples

        function = resolve_function(function)
        examples = read_examples(path)
        if not replace:
            return {
                "function_id": function,
                "rows": len(examples),
                "mode": "replace",
                "status": "confirmation_required",
            }, 3
        detail = self.detail(function)
        state = self.association.read()
        run_id = state.get("run_id") if state.get("function_id") == function else None
        if run_id:
            evidence_digest = digest(examples)
            same = state.get("evidence_digest") == evidence_digest
            command = state.get("evaluation_command_id") if same else None
            revision = state.get("evaluation_revision") if command else detail["revision"]
            command = command or str(uuid4())
            self.association.update(
                evidence_digest=evidence_digest,
                evidence_file=str(Path(path).resolve()),
                evaluation_command_id=command,
                evaluation_revision=revision,
            )
            result = self.request(
                "POST",
                f"{FUNCTIONS}/{function}/evaluation/examples",
                {
                    "command_id": command,
                    "run_id": run_id,
                    "expected_revision": revision,
                    "examples": examples,
                },
            )
            return {
                "function_id": function,
                "run_id": run_id,
                "evaluation_command_id": result["id"],
                "state": result["state"],
            }, 0
        source = detail["source"]
        if source.get("version") != "function-spec-v1":
            raise SeldonContractError("draft_evaluation_requires_full_source")
        source = {
            **source,
            "evaluation": {**(source.get("evaluation") or {}), "examples": examples},
        }
        result = self.request(
            "PATCH",
            f"{FUNCTIONS}/{function}",
            {"name": detail["name"], "expected_revision": detail["revision"], "source": source},
        )
        self.association.update(
            evidence_digest=digest(examples),
            evidence_file=str(Path(path).resolve()),
            revision=result["revision"],
        )
        return {"function_id": function, "revision": result["revision"], "rows": len(examples)}, 0
