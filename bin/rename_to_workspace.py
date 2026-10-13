#!/usr/bin/env python3
"""Rewrite team names to workspace names across the tree.

Run it again after merging master and it renames whatever your branch added:

    uv run python bin/rename_to_workspace.py

Every rule is idempotent. Migrations and ADRs are never touched, and neither is
a line carrying the KEEP marker: the aliases that keep the old names working,
and the tests that pin them.
"""

import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = "rename-to-workspace: keep"
GLOBS = (
    "sbomify/**/*.py",
    "sbomify/**/*.j2",
    "sbomify/**/*.html",
    "sbomify/**/*.txt",
    "sbomify/**/*.json",
    "sbomify/**/*.ts",
    "AGENTS.md",
    "docs/**/*.md",
    "docs/**/*.csv",
)
SKIP = ("/migrations/", "docs/adr/", "/node_modules/", "/staticfiles/")


def _teams_url_names() -> str:
    source = (ROOT / "sbomify/apps/teams/urls.py").read_text()
    return "|".join(sorted(set(re.findall(r'name="([a-z_0-9]+)"', source))))


# Appended to by each phase of the rename, in the order they landed.
RULES: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    # P2a: the URL namespace, only before a name the workspaces urlconf defines.
    (re.compile(rf"\bteams:(?=(?:{_teams_url_names()})\b)"), "workspaces:"),
    # P2a: the role settings.
    (re.compile(r"\bTEAMS_(SUPPORTED|INVITABLE)_ROLES\b"), r"WORKSPACE_\1_ROLES"),
    # P2b: the URL converter, and the kwarg a {% url %} tag passes to it.
    (re.compile(r"<(str:)?team_key>"), r"<\1workspace_key>"),
    (re.compile(r"{%\s*url\b[^%]*%}"), lambda m: re.sub(r"\bteam_key=", "workspace_key=", m.group(0))),
    # P2b: spotlight destinations name the URL kwargs they fill.
    (re.compile(r'(?<="args": \[)"team_key"'), '"workspace_key"'),
    (re.compile(r"'team_key'(?= is the only one supported)"), "'workspace_key'"),
]

# P2b renames the Python name team_key, except where it is part of the wire:
# a v1 route's parameters (v2 already renames them through a wrapper), the
# fields of a class that declares team_key (request and response schemas), and
# every string key that is not a URL kwarg (Stripe metadata, analytics
# properties, response bodies, form and query fields).
OLD_NAME, NEW_NAME = "team_key", "workspace_key"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "api_operation"}
URL_KWARG_STRING_FILES = ("sbomify/apps/core/spotlight.py",)


def _is_route(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_METHODS
        for d in node.decorator_list
    )


def _callee(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def kept_callees(trees: list[ast.AST]) -> set[str]:
    """Routes and classes whose team_key is a wire name: a call to one keeps its keyword."""
    names = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_route(node):
                names.add(node.name)
            elif isinstance(node, ast.ClassDef) and any(
                isinstance(item, ast.AnnAssign) and getattr(item.target, "id", None) == OLD_NAME for item in node.body
            ):
                names.add(node.name)
    return names


def _names_url_kwarg(node: ast.Constant, parents: dict[ast.AST, ast.AST], relative: str) -> bool:
    if relative in URL_KWARG_STRING_FILES:
        return True
    parent = parents.get(node)
    owner = parents.get(parent) if parent is not None else None
    if isinstance(parent, ast.Dict) and isinstance(owner, ast.keyword):
        call = parents.get(owner)
        first = call.args[0] if isinstance(call, ast.Call) and call.args else None
        url_name = first.value if isinstance(first, ast.Constant) else ""
        # A v1 API route keeps {team_key} in its path; v2 already says workspace_key.
        return owner.arg == "kwargs" and not str(url_name).startswith("api-1:")
    if isinstance(parent, ast.Dict):
        # Climb out of a lookup table of kwargs ({...}[arg]) to what it is assigned to.
        while isinstance(owner, (ast.Dict, ast.Subscript)):
            owner = parents.get(owner)
        if isinstance(owner, ast.Assign):
            return any(ast.unparse(target).endswith("kwargs") for target in owner.targets)
    if isinstance(parent, ast.Dict) and isinstance(owner, ast.Call):
        return _callee(owner) == "ResolverMatch" and owner.args[2:3] == [parent]
    if isinstance(parent, ast.Subscript):
        return ast.unparse(parent.value).endswith("kwargs")
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and parent.args[:1] == [node]:
        return parent.func.attr in {"get", "setdefault", "pop"} and ast.unparse(parent.func.value).endswith("kwargs")
    if isinstance(parent, ast.Compare) and parent.left is node:
        return all(ast.unparse(c).endswith("kwargs") for c in parent.comparators)
    return False


def rename_python_name(text: str, tree: ast.AST, keep: set[str], relative: str) -> str:
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def in_route(node: ast.AST) -> bool:
        while node in parents:
            node = parents[node]
            if _is_route(node):
                return True
        return False

    def is_field(node: ast.AST) -> bool:
        owner = parents.get(node)
        return isinstance(owner, (ast.AnnAssign, ast.Assign)) and isinstance(parents.get(owner), ast.ClassDef)

    spans = []  # (line, start byte, the old text, replacement)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.arg)) and getattr(node, "id", getattr(node, "arg", None)) == OLD_NAME:
            if not in_route(node) and not is_field(node):
                spans.append((node.lineno, node.col_offset, OLD_NAME, NEW_NAME))
        elif isinstance(node, ast.keyword) and node.arg == OLD_NAME:
            call = parents[node]
            if not isinstance(call, ast.Call) or _callee(call) not in keep:
                spans.append((node.lineno, node.col_offset, OLD_NAME, NEW_NAME))
        elif isinstance(node, ast.Constant) and node.value == OLD_NAME and _names_url_kwarg(node, parents, relative):
            spans.append((node.lineno, node.col_offset + 1, OLD_NAME, NEW_NAME))

    lines = text.encode().splitlines(keepends=True)
    for lineno, start, old, new in sorted(spans, reverse=True):
        line = lines[lineno - 1]
        if KEEP.encode() in line or line[start : start + len(old)] != old.encode():
            continue
        lines[lineno - 1] = line[:start] + new.encode() + line[start + len(old) :]
    return b"".join(lines).decode()


def rewrite(text: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if KEEP in line:
            continue
        for pattern, replacement in RULES:
            line = pattern.sub(replacement, line)
        lines[i] = line
    return "".join(lines)


def _paths() -> list[tuple[Path, str]]:
    found = []
    for glob in GLOBS:
        for path in sorted(ROOT.glob(glob)):
            relative = path.relative_to(ROOT).as_posix()
            if not any(part in f"/{relative}" for part in SKIP) and path.is_file():
                found.append((path, relative))
    return found


def main() -> None:
    paths = _paths()
    trees = {path: ast.parse(path.read_text()) for path, _ in paths if path.suffix == ".py"}
    keep = kept_callees(list(trees.values()))
    changed = 0
    for path, relative in paths:
        text = path.read_text()
        new = rename_python_name(text, trees[path], keep, relative) if path in trees else text
        new = rewrite(new)
        if new != text:
            path.write_text(new)
            changed += 1
            sys.stdout.write(f"{relative}\n")
    sys.stdout.write(f"{changed} files rewritten\n")


if __name__ == "__main__":
    main()
