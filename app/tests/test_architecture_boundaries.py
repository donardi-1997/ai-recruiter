"""Architecture dependency guards for the modular monolith foundation."""

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]

CRUD_ROUTER_ALLOWLIST = {
    "domains/jobs/router.py",
    "domains/evaluations/router.py",
    "domains/ranking/router.py",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result.add(module)
            if module:
                result.update(f"{module}.{alias.name}" for alias in node.names)

    return result


def _python_files(root: Path):
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_import_parser_qualifies_from_import_symbols(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from app.deps import acquire_job_lock\n",
        encoding="utf-8",
    )

    assert "app.deps.acquire_job_lock" in _imports(sample)


def test_only_documented_transitional_routers_import_app_crud():
    violations = []
    routers = APP_ROOT / "domains"

    for path in routers.rglob("router.py"):
        relative = path.relative_to(APP_ROOT).as_posix()
        if "app.crud" in _imports(path) and relative not in CRUD_ROUTER_ALLOWLIST:
            violations.append(relative)

    assert violations == []


def test_domain_non_router_modules_do_not_import_domain_routers():
    violations = []

    for path in _python_files(APP_ROOT / "domains"):
        if path.name == "router.py":
            continue
        if any(
            name.endswith(".router") and name.startswith("app.domains.")
            for name in _imports(path)
        ):
            violations.append(path.relative_to(APP_ROOT).as_posix())

    assert violations == []


def test_infrastructure_does_not_import_domain_routers():
    violations = []

    for path in _python_files(APP_ROOT / "infrastructure"):
        if any(
            name.endswith(".router") and name.startswith("app.domains.")
            for name in _imports(path)
        ):
            violations.append(path.relative_to(APP_ROOT).as_posix())

    assert violations == []


def test_locking_is_not_imported_from_deps_outside_http_adapters():
    violations = []
    forbidden = {
        "app.deps.acquire_job_lock",
        "app.deps.release_job_lock",
        "app.deps._advisory_lock_key",
    }

    for path in _python_files(APP_ROOT):
        if path == APP_ROOT / "deps.py":
            continue
        if _imports(path) & forbidden:
            violations.append(path.relative_to(APP_ROOT).as_posix())

    assert violations == []


def test_deps_does_not_reexport_locking_infrastructure():
    imports = _imports(APP_ROOT / "deps.py")
    assert not any(name.startswith("app.infrastructure.locking") for name in imports)
