"""Conservative AST discovery. No imports, prompt output, network or volume estimates."""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def scan(
    path: str | Path, *, suggest: bool = False, format: str = "existing"
) -> dict[str, list[dict[str, Any]]]:
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    rows = []
    for file in files:
        if any(part in EXCLUDED for part in file.parts):
            continue
        if file.stat().st_size > 1_048_576:
            continue
        try:
            tree = ast.parse(file.read_text())
        except (SyntaxError, UnicodeError):
            continue
        constants, aliases, clients, parents = {}, {}, {}, {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
            if isinstance(parent, ast.ImportFrom):
                for item in parent.names:
                    aliases[item.asname or item.name] = (parent.module or "") + "." + item.name
            elif isinstance(parent, ast.Import):
                for item in parent.names:
                    aliases[item.asname or item.name] = item.name
            elif isinstance(parent, ast.Assign):
                for target in parent.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(parent.value, ast.Constant) and isinstance(
                            parent.value.value, str
                        ):
                            constants[target.id] = parent.value.value
                        elif isinstance(parent.value, ast.Call):
                            clients[target.id] = ast.unparse(parent.value.func)

        def ancestry(node: ast.AST, parents: dict[ast.AST, ast.AST] = parents) -> Iterator[ast.AST]:
            while node in parents:
                node = parents[node]
                yield node

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            parts = name.split(".")
            root = clients.get(parts[0], aliases.get(parts[0], parts[0]))
            resolved = aliases.get(root, root) + "." + ".".join(parts[1:])
            lower = resolved.lower()
            framework = None
            if parts[-1] in {"create", "parse"} and (
                "openai" in lower or ".chat.completions." in name or ".responses." in name
            ):
                framework = "openai"
            elif parts[-1] in {"completion", "acompletion"} and "litellm" in lower:
                framework = "litellm"
            elif parts[-1] in {"invoke", "ainvoke", "with_structured_output"} and (
                "langchain" in lower or "chatopenai" in lower or parts[0] in clients
            ):
                framework = "langchain"
            elif parts[-1] == "Agent" and "pydantic_ai" in lower:
                framework = "pydantic_ai"
            if framework is None:
                continue
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            reasons = []
            stream = keywords.get("stream")
            if isinstance(stream, ast.Constant) and stream.value:
                reasons.append("streaming")
            if "tools" in keywords:
                reasons.append("tool_use")
            if "message_history" in keywords or any(
                isinstance(parent, (ast.For, ast.While, ast.AsyncFor)) for parent in ancestry(node)
            ):
                reasons.append("conversation_history")
            source = None
            for candidate in ast.walk(node):
                if isinstance(candidate, ast.Name) and candidate.id in constants:
                    source = candidate.id
                    break
            structured = (
                "schema"
                if set(keywords) & {"response_format", "output_type", "result_type"}
                or parts[-1] in {"parse", "with_structured_output"}
                else "none"
            )
            if any(
                isinstance(value, ast.Name) and value.id == "str"
                for key in ("output_type", "result_type")
                for value in (keywords.get(key),)
            ):
                structured = "text"
            if source is None:
                reasons.append("dynamic_prompt")
            eligibility = (
                "out_of_scope"
                if any(
                    reason in reasons
                    for reason in ("streaming", "tool_use", "conversation_history")
                )
                else "needs_change"
                if "dynamic_prompt" in reasons
                else "eligible"
            )
            row = {
                "file": str(file),
                "line": node.lineno,
                "framework": framework,
                "structured_output": structured,
                "template_source": source,
                "eligibility": eligibility,
                "reasons": reasons,
            }
            if suggest and eligibility == "eligible":
                row["suggestion"] = (
                    "seldon import --source operation.json; "
                    "replace selected call model with its Function alias"
                )
                if format == "sdk":
                    row["suggestion"] = (
                        "Use @seldon.function with the selected fixed template "
                        "and explicit typed parameters"
                    )
                    row["render_differences"] = (
                        "Non-string inputs use canonical JSON; review against str.format"
                    )
            rows.append(row)
    order = {"eligible": 0, "needs_change": 1, "out_of_scope": 2}
    return {
        "items": sorted(
            rows,
            key=lambda item: (
                order[item["eligibility"]],
                item["structured_output"] == "none",
                item["template_source"] is None,
                item["file"],
                item["line"],
            ),
        )
    }
