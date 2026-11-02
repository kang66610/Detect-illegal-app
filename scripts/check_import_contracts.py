"""校验全仓 `from X import Y` 的 Y 在 X 里确实存在。

删未使用导入时最容易踩的坑：某个名字在模块内没用到，但被别的模块
（或测试）import 走了（facade / re-export）。ruff 的 F401 看不到这一点。
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def exported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
    return names


def main() -> None:
    files = [
        p for p in ROOT.rglob("*.py")
        if not {".venv", "__pycache__", ".worktrees"} & set(p.parts)
    ]
    exports: dict[str, set[str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        exports[module_name(path)] = exported_names(tree)

    missing: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            if node.module not in exports:
                continue
            package_dir = ROOT / Path(*node.module.split("."))
            for alias in node.names:
                if alias.name == "*":
                    continue
                # `from pkg import submodule` is legal even when pkg/__init__
                # never names it, so only flag real missing attributes.
                if (package_dir / f"{alias.name}.py").exists():
                    continue
                if (package_dir / alias.name / "__init__.py").exists():
                    continue
                if alias.name not in exports[node.module]:
                    missing[(node.module, alias.name)].add(module_name(path))

    if not missing:
        print("OK: 所有 from-import 目标都存在")
        return
    print(f"发现 {len(missing)} 个缺失的导入目标：")
    for (module, name), users in sorted(missing.items()):
        print(f"  {module}.{name}  <- {', '.join(sorted(users))[:120]}")


if __name__ == "__main__":
    main()
