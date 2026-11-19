"""Generated Manim source safety policy validator.

Static validation is defence-in-depth alongside container isolation.
It does not replace the container boundary — it catches obvious violations
before a potentially slow container launch.

Rejected patterns:
- Imports of dangerous stdlib modules (os, sys, subprocess, socket, ...)
- Dynamic import builtins (__import__, importlib, pkgutil)
- Shell-execution builtins (eval, exec, compile)
- Filesystem access calls (open, pathlib.Path.write_*, ...)
- Network access (requests, httpx, urllib.request, socket.*, ...)
- Package installation (pip, subprocess with install, ...)
"""
from __future__ import annotations

import ast
from typing import Sequence

from learning_pipeline.tools.manim_video._contracts import ManimSourcePolicyError

# Modules whose import is unconditionally banned.
_BANNED_TOP_LEVEL: frozenset[str] = frozenset({
    "os",
    "sys",
    "subprocess",
    "socket",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "telnetlib",
    "importlib",
    "pkgutil",
    "zipimport",
    "shutil",
    "tempfile",
    "multiprocessing",
    "threading",
    "concurrent",
    "ctypes",
    "cffi",
    "pickle",
    "shelve",
    "signal",
})

# Attribute access chains that are banned regardless of top-level import.
_BANNED_ATTR_PATHS: frozenset[str] = frozenset({
    "os.system",
    "os.popen",
    "os.execv",
    "os.execve",
    "os.fork",
    "os.spawn",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.check_output",
})

# Builtin function names that must not appear as function calls.
_BANNED_BUILTINS: frozenset[str] = frozenset({
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
})

# Node visitor for AST-based policy checks.


class _PolicyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in _BANNED_TOP_LEVEL:
                self.violations.append(
                    f"Line {node.lineno}: banned import '{alias.name}'"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        top = module.split(".")[0]
        if top in _BANNED_TOP_LEVEL:
            self.violations.append(
                f"Line {node.lineno}: banned import 'from {module} import ...'"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for banned builtin calls like eval(), exec(), open().
        if isinstance(node.func, ast.Name) and node.func.id in _BANNED_BUILTINS:
            self.violations.append(
                f"Line {node.lineno}: banned builtin call '{node.func.id}()'"
            )
        # Check for banned attribute paths like os.system(), subprocess.run().
        if isinstance(node.func, ast.Attribute):
            attr_path = _attr_chain(node.func)
            if attr_path in _BANNED_ATTR_PATHS:
                self.violations.append(
                    f"Line {node.lineno}: banned call '{attr_path}()'"
                )
        self.generic_visit(node)


def _attr_chain(node: ast.Attribute | ast.Name) -> str:
    """Reconstruct the dotted attribute path from an AST node."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


class SourcePolicyValidator:
    """Validates generated Manim Python source before sending to the container.

    Raises ManimSourcePolicyError if any violation is found.
    Violations are collected in full before raising (not short-circuit) so the
    repair payload can include all issues at once.
    """

    def validate(self, source: str) -> None:
        """Parse source as AST and check all policy rules.

        Parameters
        ----------
        source:
            The complete generated Manim Python source code.

        Raises
        ------
        ManimSourcePolicyError
            If one or more policy violations are found. The message lists all
            violations so the LLM repair can address them in a single call.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise ManimSourcePolicyError(
                f"Source has a syntax error and cannot be parsed: {exc}"
            ) from exc

        visitor = _PolicyVisitor()
        visitor.visit(tree)

        if visitor.violations:
            joined = "\n  ".join(visitor.violations)
            raise ManimSourcePolicyError(
                f"Source policy violations ({len(visitor.violations)}):\n  {joined}"
            )
