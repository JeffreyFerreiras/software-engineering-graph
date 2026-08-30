"""Read-only hygiene checks for the authoritative repository checkout."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROFILE_AGENTS = {
    "impact_mapper.toml",
    "tech_lead.toml",
    "software_architect.toml",
    "senior_engineer.toml",
    "code_reviewer.toml",
    "test_engineer.toml",
    "security_reviewer.toml",
}
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
AUTHORITY_DOCUMENTS = ("README.md", "AGENTS.md", "docs/technical-design.md")
STALE_EXTERNAL_REQUIREMENTS = (
    "seg_source_skill", "seg_source_agents", "source parity", "byte parity",
    "approved profile skill", "detached source inputs",
)


class StandaloneAcceptanceTests(unittest.TestCase):
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

        profile_root = REPOSITORY_ROOT / "profile-agents"
        self.assertEqual(PROFILE_AGENTS, {path.name for path in profile_root.iterdir()})
        self.assertTrue(all(path.is_file() for path in profile_root.iterdir()))

        for name in AUTHORITY_DOCUMENTS:
            content = " ".join(
                (REPOSITORY_ROOT / name).read_text(encoding="utf-8").lower().split()
            )
            with self.subTest(authority_document=name):
                self.assertIn("repository is authoritative", content)
                self.assertIn("installed profile remains untouched", content)
                for stale in STALE_EXTERNAL_REQUIREMENTS:
                    self.assertNotIn(stale, content)

        skill_heading = next(
            line for line in (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("# ")
        )
        self.assertEqual("# Software Engineering Graph", skill_heading)

        skill_guidance = " ".join(
            (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8").lower().split()
        )
        senior_guidance = " ".join(
            (profile_root / "senior_engineer.toml").read_text(encoding="utf-8").lower().split()
        )
        reviewer_guidance = " ".join(
            (profile_root / "code_reviewer.toml").read_text(encoding="utf-8").lower().split()
        )
        for name, guidance in (
            ("skill", skill_guidance),
            ("senior engineer", senior_guidance),
            ("code reviewer", reviewer_guidance),
        ):
            with self.subTest(skill_discovery_guidance=name):
                self.assertIn("skill catalog exposed", guidance)
                self.assertIn("local skills explicitly declared", guidance)
                self.assertIn("smallest clearly relevant skill set", guidance)
                self.assertIn("selected skill", guidance)
                self.assertIn("fully before act", guidance)
                self.assertIn("do not prescribe a specific optional skill by name", guidance)
                self.assertIn("do not crawl arbitrary profile or global skill directories", guidance)
                self.assertIn("may change", guidance)
                self.assertIn("method only", guidance)
                self.assertIn("scope", guidance)
                self.assertIn("role authority", guidance)
                self.assertIn("model or reasoning effort", guidance)
                self.assertIn("writable files", guidance)
                self.assertIn("allowed tests or commands", guidance)
                self.assertIn("delegation", guidance)
                self.assertIn("external effects", guidance)
                self.assertIn("install", guidance)
                self.assertIn("synchroniz", guidance)
                self.assertIn("remove", guidance)
                self.assertIn("profiles", guidance)
                self.assertIn("consumer repositories", guidance)
                self.assertIn("user instructions", guidance)
                self.assertIn("repository instructions", guidance)
                self.assertIn("approved task artifacts", guidance)
                self.assertIn("control", guidance)
                self.assertIn("catalog is unavailable", guidance)
                self.assertTrue(
                    "unreadable" in guidance or "cannot be read" in guidance,
                    "missing selected-skill read-failure guidance in {}".format(name),
                )
                self.assertIn("skill usage", guidance)
                self.assertIn("safe source or provenance", guidance)
                self.assertIn("relevance reason", guidance)
                self.assertIn("none", guidance)

        self.assertNotIn("every role handoff", skill_guidance)
        self.assertIn(
            "senior engineer and code reviewer handoffs must each include a `skill usage` section",
            skill_guidance,
        )
        self.assertIn("sole production-code and test-code writer", senior_guidance)
        self.assertIn('sandbox_mode = "workspace-write"', senior_guidance)
        self.assertIn('sandbox_mode = "read-only"', reviewer_guidance)
        self.assertIn("remain read-only", reviewer_guidance)
        for name in AUTHORITY_DOCUMENTS:
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
