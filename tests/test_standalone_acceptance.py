"""Source-only acceptance checks for the standalone workflow checkout."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {".gitignore", "AGENTS.md", "README.md", "SKILL.md"}
SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "graph_engine/__init__.py",
    "graph_engine/cli.py",
    "graph_engine/config.py",
    "graph_engine/contracts.py",
    "graph_engine/evidence.py",
    "graph_engine/ids.py",
    "graph_engine/planner.py",
    "graph_engine/state.py",
    "graph_engine/validator.py",
    "references/branch-envelope.schema.json",
    "references/impact-map.schema.json",
    "references/repository-config.schema.json",
    "references/task-brief.schema.json",
    "scripts/graphctl.py",
    "tests/test_cli.py",
    "tests/test_contracts.py",
    "tests/test_planner.py",
    "tests/test_state.py",
    "tests/test_support.py",
    "tests/test_validator.py",
    "tests/fixtures/result-manifests/golden-traces.json",
)
PROFILE_AGENTS = (
    "impact_mapper.toml",
    "tech_lead.toml",
    "software_architect.toml",
    "senior_engineer.toml",
    "code_reviewer.toml",
    "test_engineer.toml",
    "security_reviewer.toml",
)
COPIED_ROOTS = ("agents", "graph_engine", "references", "scripts", "tests")
SOURCE_EXCLUDED_DIRECTORIES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
    ".venv", "venv", "env", "htmlcov", "build", "dist", "graph-runs", "graph-inbox",
}
REQUIRED_IGNORE_PATTERNS = {
    "__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    ".tox/", ".nox/", ".venv/", "venv/", "env/", ".coverage", ".coverage.*",
    "htmlcov/", "build/", "dist/", "*.egg-info/", ".env", ".env.*", "*.key",
    "*.pem", "*.crt", "*.cer", "*.p12", "*.pfx", "*.db", "*.sqlite",
    "*.sqlite3", "*.sqlite3-*", "graph-runs/", "graph-inbox/", "*.tmp", "*.temp",
    "*.bak", "*~",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_within(candidate, parent):
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalized_skill_bytes(source):
    original = source.read_bytes()
    old_heading = b"# Software Engineering Graph v2"
    new_heading = b"# Software Engineering Graph"
    if original.count(old_heading) != 1:
        raise AssertionError("source SKILL.md does not contain exactly one approved heading")
    return original.replace(old_heading, new_heading, 1)


class StandaloneAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_skill = cls._required_external_directory("SEG_SOURCE_SKILL")
        cls.source_agents = cls._required_external_directory("SEG_SOURCE_AGENTS")

    @classmethod
    def _required_external_directory(cls, variable):
        value = os.environ.get(variable)
        if not value:
            raise AssertionError("{} must name an explicit source directory".format(variable))
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise AssertionError("{} is not a directory: {}".format(variable, path))
        if _is_within(path, REPOSITORY_ROOT) or _is_within(REPOSITORY_ROOT, path):
            raise AssertionError("{} must not overlap the destination repository".format(variable))
        return path

    def _source_snapshot(self):
        snapshot = {}
        for relative in SKILL_FILES:
            path = self.source_skill / relative
            self.assertTrue(path.is_file(), "missing source skill file: {}".format(relative))
            snapshot["skill/" + relative] = _sha256(path)
        for name in PROFILE_AGENTS:
            path = self.source_agents / name
            self.assertTrue(path.is_file(), "missing source profile agent: {}".format(name))
            snapshot["agent/" + name] = _sha256(path)
        return snapshot

    def test_source_parity(self):
        actual_root_files = {path.name for path in REPOSITORY_ROOT.iterdir() if path.is_file()}
        self.assertEqual(ROOT_FILES, actual_root_files)

        expected = set(SKILL_FILES)
        actual = {"SKILL.md"}
        for root_name in COPIED_ROOTS:
            root = REPOSITORY_ROOT / root_name
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(REPOSITORY_ROOT).as_posix()
                if relative != "tests/test_standalone_acceptance.py":
                    actual.add(relative)
        self.assertEqual(expected, actual)

        for relative in SKILL_FILES:
            source = self.source_skill / relative
            destination = REPOSITORY_ROOT / relative
            self.assertTrue(source.is_file(), "missing source skill file: {}".format(relative))
            self.assertTrue(destination.is_file(), "missing destination skill file: {}".format(relative))
            if relative == "SKILL.md":
                self.assertEqual(_normalized_skill_bytes(source), destination.read_bytes())
            else:
                self.assertEqual(source.stat().st_size, destination.stat().st_size, relative)
                self.assertEqual(_sha256(source), _sha256(destination), relative)

        profile_root = REPOSITORY_ROOT / "profile-agents"
        actual_agents = {path.name for path in profile_root.iterdir() if path.is_file()}
        actual_entries = {path.name for path in profile_root.iterdir()}
        self.assertEqual(set(PROFILE_AGENTS), actual_agents)
        self.assertEqual(set(PROFILE_AGENTS), actual_entries)
        for name in PROFILE_AGENTS:
            source = self.source_agents / name
            destination = profile_root / name
            self.assertEqual(source.stat().st_size, destination.stat().st_size, name)
            self.assertEqual(_sha256(source), _sha256(destination), name)

    def test_imports_and_help_do_not_mutate_sources(self):
        before_sources = self._source_snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve()
            for protected in (self.source_skill, self.source_agents, REPOSITORY_ROOT):
                self.assertFalse(_is_within(temporary_root, protected))
                self.assertFalse(_is_within(protected, temporary_root))

            environment = os.environ.copy()
            environment.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "CODEX_HOME": str(temporary_root),
                "TEMP": str(temporary_root),
                "TMP": str(temporary_root),
            })
            modules = (
                "graph_engine", "graph_engine.cli", "graph_engine.config",
                "graph_engine.contracts", "graph_engine.evidence", "graph_engine.ids",
                "graph_engine.planner", "graph_engine.state", "graph_engine.validator",
            )
            subprocess.run(
                [sys.executable, "-c", "; ".join("import " + name for name in modules)],
                cwd=str(REPOSITORY_ROOT),
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            help_result = subprocess.run(
                [sys.executable, "scripts/graphctl.py", "--help"],
                cwd=str(REPOSITORY_ROOT),
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("usage:", help_result.stdout.lower())
            self.assertEqual([], list(temporary_root.rglob("*")))

        self.assertEqual(before_sources, self._source_snapshot())

    def test_hygiene(self):
        forbidden = []
        for path in REPOSITORY_ROOT.rglob("*"):
            relative = path.relative_to(REPOSITORY_ROOT)
            if relative.parts and relative.parts[0] == ".git":
                continue
            if path.is_dir() and (
                path.name in SOURCE_EXCLUDED_DIRECTORIES or path.name.lower().endswith(".egg-info")
            ):
                forbidden.append(relative.as_posix() + "/")
                continue
            if not path.is_file():
                continue
            name = path.name.lower()
            suffix = path.suffix.lower()
            if (
                suffix in {".pyc", ".pyo", ".pyd", ".db", ".sqlite", ".sqlite3", ".key",
                           ".pem", ".crt", ".cer", ".p12", ".pfx", ".tmp", ".temp", ".bak"}
                or name == ".coverage"
                or name.startswith(".coverage.")
                or name == ".env"
                or name.startswith(".env.")
                or ".sqlite3-" in name
                or name.endswith("~")
            ):
                forbidden.append(relative.as_posix())
        self.assertEqual([], sorted(forbidden))

        ignored = {
            line.strip() for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(set(), REQUIRED_IGNORE_PATTERNS - ignored)

        skill_heading = next(
            line for line in (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("# ")
        )
        self.assertEqual("# Software Engineering Graph", skill_heading)
        for name in ("README.md", "AGENTS.md", "docs/technical-design.md"):
            headings = [
                line.lower() for line in (REPOSITORY_ROOT / name).read_text(encoding="utf-8").splitlines()
                if line.startswith("#")
            ]
            self.assertFalse(
                any("software engineering graph v" in heading for heading in headings),
                "version-generation branding in {}".format(name),
            )


if __name__ == "__main__":
    unittest.main()
