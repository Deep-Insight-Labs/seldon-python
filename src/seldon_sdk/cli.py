"""One CLI for explicit source preparation, comparison, adoption and local execution."""

import argparse
import asyncio
import importlib.resources
import json
import os
import sys

import httpx

from . import __version__
from .auth import DEFAULT_BASE_URL, Login, base_url
from .errors import SeldonError
from .files import Association, atomic_json, digest, read_json, resolve_function, validate_source
from .management import Management


def parser():
    root = argparse.ArgumentParser(prog="seldon")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--base-url", default=os.environ.get("SELDON_BASE_URL", DEFAULT_BASE_URL))
    root.add_argument("--profile", default="default")
    root.add_argument("--association", default=".seldon/operation.json")
    commands = root.add_subparsers(dest="command", required=True)
    source = commands.add_parser(
        "import", help="Validate an explicit source file; import with a login"
    )
    source.add_argument("--source", required=True)
    source.add_argument("--function")
    source.add_argument("--name", default="Selected operation")
    source.add_argument("--offline", action="store_true")
    for name in ("login", "whoami"):
        commands.add_parser(name)
    logout = commands.add_parser("logout")
    logout.add_argument("--all-profiles", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("function", nargs="?")
    status.add_argument("--json", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("function")
    report.add_argument("--run")
    report.add_argument("--json", action="store_true")
    optimize = commands.add_parser("optimize")
    optimize.add_argument("function")
    optimize.add_argument("--cap", required=True)
    optimize.add_argument("--objective", choices=("cost", "latency", "quality"), default="cost")
    optimize.add_argument("--max-p95-ms", type=float)
    optimize.add_argument("--yes", action="store_true")
    optimize.add_argument("--wait", action="store_true")
    optimize.add_argument("--new-run", action="store_true")
    optimize.add_argument("--source-run")
    optimize.add_argument("--timeout", type=float, default=600)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("function")
    cancel.add_argument("--run", required=True)
    ready = commands.add_parser("reference-readiness")
    ready.add_argument("function")
    reference = commands.add_parser("serve-reference")
    reference.add_argument("function")
    reference.add_argument("--acknowledge-deadline-risk", action="store_true")
    for name in ("activate", "publish"):
        action = commands.add_parser(name)
        action.add_argument("function")
        action.add_argument("--revision", required=True)
        action.add_argument("--approve-managed-fallback", action="store_true")
    examples = commands.add_parser("examples").add_subparsers(dest="example_command", required=True)
    attach = examples.add_parser("import")
    attach.add_argument("function")
    attach.add_argument("--file", required=True)
    attach.add_argument("--replace", action="store_true")
    check = commands.add_parser("check", help="Offline source drift check")
    check.add_argument("modules", nargs="*")
    check.add_argument("--source")
    check.add_argument("--function")
    check.add_argument("--template-file")
    check.add_argument("--syntax", choices=("python_format", "jinja_variables"))
    check.add_argument("--allow-pending", action="store_true")
    check.add_argument("--offline", action="store_true")
    export = commands.add_parser("export")
    export.add_argument("modules", nargs="+")
    export.add_argument("--out", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("modules", nargs="+")
    sync.add_argument("--json", action="store_true")
    lock = commands.add_parser("lock").add_subparsers(dest="lock_command", required=True)
    set_lock = lock.add_parser("set")
    set_lock.add_argument("key")
    set_lock.add_argument("function")
    set_lock.add_argument("--module", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("path", nargs="?", default=".")
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--suggest", action="store_true")
    scan.add_argument("--format", choices=("existing", "sdk"), default="existing")
    check.add_argument("--json", action="store_true")
    local = commands.add_parser("function").add_subparsers(dest="local_command", required=True)
    for name in ("pull", "verify", "run"):
        action = local.add_parser(name)
        action.add_argument("function")
        action.add_argument("--out", default=".seldon/function-bundle.json")
        action.add_argument("--input")
        action.add_argument("--fallback", choices=("seldon", "raise"), default="seldon")
        action.add_argument("--no-telemetry", action="store_true")
    skill = commands.add_parser("skill").add_subparsers(dest="skill_command", required=True)
    skill.add_parser("print")
    return root


def emit(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


def _confirmation(summary):
    emit(summary)
    value = summary.get("revision_id") or summary["function_id"]
    return input("Type the displayed revision or Function id to confirm: ").strip() == value


def _local(args):
    identity = resolve_function(args.function)
    key = os.environ.get("SELDON_API_KEY")
    if not key:
        raise SeldonError("inference_api_key_required")
    origin = base_url(args.base_url)
    if args.local_command == "pull":
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as http:
                response = http.get(
                    f"{origin}/v1/seldon/functions/{identity}/bundle",
                    headers={"Authorization": "Bearer " + key},
                )
            if response.status_code != 200:
                raise SeldonError("bundle_unavailable", status=response.status_code)
            bundle = response.json()
            etag = response.headers.get("etag", "").strip('"')
            if (
                bundle.get("version") != "function-bundle-v1"
                or digest({k: v for k, v in bundle.items() if k != "expires_at"}) != etag
            ):
                raise SeldonError("bundle_invalid")
        except (httpx.HTTPError, ValueError):
            raise SeldonError("bundle_unavailable") from None
        atomic_json(args.out, bundle)
        return {
            "bundle_file": args.out,
            "revision_id": bundle["revision_id"],
            "verification": "not_run",
        }
    try:
        from seldon_runtime.runner import Runner
    except ImportError:
        raise SeldonError("install_seldon_runtime_gliner_extra") from None

    async def execute():
        runner = await Runner.load(
            identity,
            key,
            base_url=origin,
            fallback=args.fallback,
            allow_unverified=args.local_command == "verify",
            telemetry=not args.no_telemetry,
        )
        try:
            if args.local_command == "verify":
                result = await runner.verify()
                return {"verification": result, "status": runner.status()}
            if not args.input:
                raise SeldonError("input_file_required")
            return await runner(read_json(args.input))
        finally:
            await runner.aclose()

    return asyncio.run(execute())


def main(argv=None, *, login=None, interactive=None, confirm=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "skill":
            print(importlib.resources.files("seldon_sdk").joinpath("skill/SKILL.md").read_text())
            return 0
        if args.command == "export":
            from .preparation import exported

            result, code = exported(args.modules, args.out)
            emit(result)
            return code
        if args.command == "lock":
            from .preparation import lock_set

            emit(lock_set(args.module, args.key, args.function))
            return 0
        if args.command == "scan":
            from .scanner import scan

            emit(scan(args.path, suggest=args.suggest, format=args.format))
            return 0
        if args.command == "check" and args.modules:
            from .preparation import check_modules

            session = None if args.offline else login
            if session is None and not args.offline:
                candidate = Login(args.base_url, profile=args.profile)
                if candidate.store.get(candidate.key):
                    session = candidate
            api = Management(session, association=args.association) if session else None
            result, code = check_modules(args.modules, api=api, allow_pending=args.allow_pending)
            emit(result)
            return code
        if args.command == "check" and args.function:
            from .preparation import check_template

            if not args.template_file or not args.syntax:
                raise SeldonError("template_file_and_syntax_required")
            session = login or Login(args.base_url, profile=args.profile)
            result, code = check_template(
                Management(session), args.function, args.template_file, args.syntax
            )
            emit(result)
            return code
        if args.command == "check":
            if not args.source:
                raise SeldonError("source_or_module_required")
            source_digest = digest(validate_source(read_json(args.source)))
            state = Association(args.association).read()
            status = (
                "unchanged"
                if state.get("source_digest") == source_digest
                else "stale_lock"
                if state
                else "unregistered"
            )
            emit({"status": status, "source_digest": source_digest})
            return 0 if status == "unchanged" else 1
        if args.command == "function":
            emit(_local(args))
            return 0
        if args.command == "import" and args.offline:
            source = validate_source(read_json(args.source))
            emit(
                {
                    "status": "validated_offline",
                    "source_file": args.source,
                    "source_digest": digest(source),
                    "fields": sorted(source) if isinstance(source, dict) else ["calls"],
                    "next_action": "dashboard_import_or_login",
                }
            )
            return 0
        session = login or Login(args.base_url, profile=args.profile)
        api = Management(session, association=args.association)
        if args.command == "import":
            emit(
                api.import_source(
                    args.source, function=args.function, name=args.name, offline=args.offline
                )
            )
        elif args.command == "sync":
            from .preparation import sync_modules

            result, code = sync_modules(args.modules, api)
            emit(result)
            return code
        elif args.command == "login":
            emit(session.login(emit))
        elif args.command == "logout":
            emit(session.logout_all() if args.all_profiles else session.logout())
        elif args.command == "whoami":
            emit(session.identity())
        elif args.command == "status":
            emit(api.status(args.function))
        elif args.command == "report":
            emit(api.report(args.function, run_id=args.run))
        elif args.command == "cancel":
            emit(api.cancel(args.function, args.run))
        elif args.command == "optimize":
            result, code = api.optimize(
                args.function,
                cap=args.cap,
                objective=args.objective,
                max_p95_ms=args.max_p95_ms,
                authorize=args.yes,
                wait=args.wait,
                timeout=args.timeout,
                new_run=args.new_run,
                source_run=args.source_run,
            )
            emit(result)
            return code
        elif args.command == "reference-readiness":
            emit(
                api.request(
                    "GET",
                    "/v1/seldon/functions/"
                    + resolve_function(args.function)
                    + "/reference-readiness",
                )
            )
        elif args.command == "serve-reference":
            result, code = api.serve_reference(
                args.function,
                acknowledge_deadline_risk=args.acknowledge_deadline_risk,
                interactive=sys.stdin.isatty() if interactive is None else interactive,
                confirm=confirm or _confirmation,
            )
            emit(result)
            return code
        elif args.command in ("activate", "publish"):
            result, code = api.activate(
                args.function,
                args.revision,
                publish=args.command == "publish",
                managed_fallback_approved=args.approve_managed_fallback,
                interactive=sys.stdin.isatty() if interactive is None else interactive,
                confirm=confirm or _confirmation,
            )
            emit(result)
            return code
        elif args.command == "examples":
            result, code = api.import_examples(args.function, args.file, replace=args.replace)
            emit(result)
            return code
        return 0
    except SeldonError as exc:
        print("seldon: " + exc.code, file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, StopIteration):
        print("seldon: invalid_input_or_service_response", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("seldon: interrupted; resume the saved run, do not resubmit blindly", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
