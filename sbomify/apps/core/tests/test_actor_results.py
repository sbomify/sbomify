"""An actor that returns a value must store it, or dramatiq warns on every run."""

import ast
from pathlib import Path

import sbomify

ROOT = Path(sbomify.__file__).parent


def _returns_a_value(fn: ast.FunctionDef) -> bool:
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _unstored_actors() -> list[str]:
    offenders = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, ast.FunctionDef):
                continue
            actors = [d for d in fn.decorator_list if "dramatiq.actor" in ast.unparse(d)]
            if not actors:
                continue
            stores = any(
                kw.arg == "store_results" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
                for d in actors
                if isinstance(d, ast.Call)
                for kw in d.keywords
            )
            if not stores and _returns_a_value(fn):
                offenders.append(f"{path.relative_to(ROOT)}::{fn.name}")
    return offenders


def test_actors_without_store_results_return_none() -> None:
    assert _unstored_actors() == []
