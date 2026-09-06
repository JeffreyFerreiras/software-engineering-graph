#!/usr/bin/env python3
"""Validate a skills repository and optionally compare it with a profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as error:
    raise SystemExit("PyYAML is required. Install it with: python -m pip install PyYAML") from error


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESOURCE_REFERENCE_PATTERN = re.compile(r"`((?:scripts|references|assets)/[^`\s]+)`")
MARKDOWN_LINK_PATTERN = re.compile(r"\]\((?!https?://|mailto:|#)([^)]+)\)")
MACHINE_PATH_PATTERN = re.compile(r"[A-Za-z]:\\(?:Users|dev)\\", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
IGNORED_TREE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
TRIGGER_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "or",
    "the",
    "to",
    "use",
    "when",
    "with",
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    path: str
    message: str


@dataclass
class Audit:
    root: str
    skills: int
    issues: list[Issue]

    @property
    def errors(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warnings(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)


def add_issue(issues: list[Issue], severity: str, code: str, path: Path, message: str) -> None:
    issues.append(Issue(severity=severity, code=code, path=str(path), message=message))


def load_yaml(path: Path, issues: list[Issue]) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        add_issue(issues, "error", "invalid-yaml", path, str(error))
        return None
    if not isinstance(loaded, dict):
        add_issue(issues, "error", "invalid-yaml-shape", path, "Expected a YAML mapping.")
        return None
    return loaded


def parse_skill(path: Path, issues: list[Issue]) -> tuple[dict[str, Any], str] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        add_issue(issues, "error", "unreadable-skill", path, str(error))
        return None

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        add_issue(issues, "error", "missing-frontmatter", path, "SKILL.md must start with YAML frontmatter.")
        return None
    try:
        closing_index = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        add_issue(issues, "error", "unclosed-frontmatter", path, "YAML frontmatter is not closed.")
        return None

    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as error:
        add_issue(issues, "error", "invalid-frontmatter", path, str(error))
        return None
    if not isinstance(metadata, dict):
        add_issue(issues, "error", "invalid-frontmatter-shape", path, "Frontmatter must be a YAML mapping.")
        return None

    body = "\n".join(lines[closing_index + 1 :]).strip()
    return metadata, body


def validate_frontmatter(skill_dir: Path, metadata: dict[str, Any], body: str, issues: list[Issue]) -> str | None:
    skill_path = skill_dir / "SKILL.md"
    extra_fields = sorted(set(metadata) - {"name", "description"})
    if extra_fields:
        add_issue(
            issues,
            "error",
            "extra-frontmatter-fields",
            skill_path,
            f"Unsupported fields: {', '.join(extra_fields)}.",
        )

    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        add_issue(issues, "error", "missing-name", skill_path, "Frontmatter requires a non-empty name.")
        name = None
    elif len(name) > 64 or not NAME_PATTERN.fullmatch(name):
        add_issue(issues, "error", "invalid-name", skill_path, "Name must be lowercase hyphen-case and at most 64 characters.")
    elif name != skill_dir.name:
        add_issue(issues, "error", "name-folder-mismatch", skill_path, f"Name '{name}' does not match folder '{skill_dir.name}'.")

    if not isinstance(description, str) or not description.strip():
        add_issue(issues, "error", "missing-description", skill_path, "Frontmatter requires a non-empty description.")
    else:
        if len(description) > 1024:
            add_issue(issues, "error", "description-too-long", skill_path, "Description exceeds 1024 characters.")
        if "<" in description or ">" in description:
            add_issue(issues, "error", "description-angle-bracket", skill_path, "Description cannot contain angle brackets.")

    if not body:
        add_issue(issues, "error", "empty-body", skill_path, "Skill body cannot be empty.")
    if re.search(r"\bTODO\b", body, re.IGNORECASE):
        add_issue(issues, "error", "placeholder-content", skill_path, "Skill body contains an unresolved TODO placeholder.")
    if MACHINE_PATH_PATTERN.search(body):
        add_issue(issues, "warning", "machine-specific-path", skill_path, "Skill contains a machine-specific Windows path; confirm it is intentional.")
    return name


def validate_openai_metadata(skill_dir: Path, skill_name: str | None, issues: list[Issue]) -> None:
    metadata_path = skill_dir / "agents" / "openai.yaml"
    if not metadata_path.exists():
        add_issue(issues, "error", "missing-openai-metadata", metadata_path, "agents/openai.yaml is required by this repository.")
        return
    metadata = load_yaml(metadata_path, issues)
    if metadata is None:
        return
    interface = metadata.get("interface")
    if not isinstance(interface, dict):
        add_issue(issues, "error", "missing-interface", metadata_path, "Expected an interface mapping.")
        return
    for field in ("display_name", "short_description", "default_prompt"):
        if not isinstance(interface.get(field), str) or not interface[field].strip():
            add_issue(issues, "error", "missing-interface-field", metadata_path, f"interface.{field} is required.")
    default_prompt = interface.get("default_prompt")
    if skill_name and isinstance(default_prompt, str) and f"${skill_name}" not in default_prompt:
        add_issue(issues, "error", "stale-default-prompt", metadata_path, f"default_prompt must reference ${skill_name}.")


def validate_resource_references(skill_dir: Path, body: str, issues: list[Issue]) -> None:
    pending = [(skill_dir / "SKILL.md", body)]
    visited: set[Path] = set()
    while pending:
        document, content = pending.pop()
        if document.resolve() in visited:
            continue
        visited.add(document.resolve())
        references = set(RESOURCE_REFERENCE_PATTERN.findall(content))
        references.update(MARKDOWN_LINK_PATTERN.findall(content))
        for reference in sorted(references):
            normalized = reference.split("#", 1)[0].strip().replace("\\", "/")
            if not normalized or normalized.startswith(("/", "~", "$")) or ":" in normalized or "<" in normalized:
                continue
            target = (document.parent / normalized).resolve()
            if not target.is_relative_to(skill_dir.resolve()):
                add_issue(issues, "error", "resource-outside-skill", document, f"Bundled reference escapes skill: {normalized}")
                continue
            if not target.exists():
                add_issue(issues, "error", "missing-resource", document, f"Referenced resource does not exist: {normalized}")
            elif target.suffix.lower() == ".md" and target.is_file():
                try:
                    pending.append((target, target.read_text(encoding="utf-8")))
                except (OSError, UnicodeError) as error:
                    add_issue(issues, "error", "unreadable-resource", target, str(error))


def validate_python(skill_dir: Path, issues: list[Issue]) -> None:
    for path in sorted(skill_dir.rglob("*.py")):
        if any(part in IGNORED_TREE_PARTS for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as error:
            add_issue(issues, "error", "invalid-python", path, str(error))


def trigger_tokens(description: str) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(description.lower()) if token not in TRIGGER_STOP_WORDS}


def validate_trigger_overlap(descriptions: dict[str, str], skills_root: Path, issues: list[Issue]) -> None:
    names = sorted(descriptions)
    for index, first_name in enumerate(names):
        first_tokens = trigger_tokens(descriptions[first_name])
        for second_name in names[index + 1 :]:
            second_tokens = trigger_tokens(descriptions[second_name])
            union = first_tokens | second_tokens
            if not union:
                continue
            similarity = len(first_tokens & second_tokens) / len(union)
            if similarity >= 0.65:
                add_issue(
                    issues,
                    "warning",
                    "overlapping-triggers",
                    skills_root,
                    f"{first_name} and {second_name} descriptions have {similarity:.0%} token overlap.",
                )


def validate_catalog(repository_root: Path, skill_names: set[str], issues: list[Issue]) -> None:
    readme_path = repository_root / "README.md"
    if not readme_path.is_file():
        add_issue(issues, "warning", "missing-readme", readme_path, "README.md is missing; the skill catalog cannot be verified.")
        return
    content = readme_path.read_text(encoding="utf-8")
    catalog_names = set(re.findall(r"^\| `([^`]+)` \|", content, re.MULTILINE))
    for name in sorted(skill_names - catalog_names):
        add_issue(issues, "error", "catalog-missing-skill", readme_path, f"Skill catalog is missing: {name}")
    for name in sorted(catalog_names - skill_names):
        add_issue(issues, "warning", "catalog-extra-skill", readme_path, f"Skill catalog contains an unknown skill: {name}")


def cursor_discovery_skill_names(discovery_root: Path) -> set[str]:
    return {
        path.name
        for path in discovery_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }


def validate_cursor_cloud_discovery(repository_root: Path, skills_root: Path, skill_names: set[str], issues: list[Issue]) -> None:
    """Ensure Cursor Cloud can discover project skills from a supported path.

    Cloud Agents do not receive local ~/.cursor/skills. They load project skills from
    .cursor/skills (and a few compatibility roots). This repository keeps canonical
    content under skills/ and exposes it through .cursor/skills.
    """
    discovery_path = repository_root / ".cursor" / "skills"
    # Git can materialize its tracked symlink as a text file on Windows.
    fallback = repository_root / ".agents" / "skills"
    if discovery_path.is_file() and discovery_path.read_text(encoding="utf-8").strip() == "../skills" and fallback.is_dir():
        discovery_path = fallback
    if not discovery_path.exists():
        add_issue(
            issues,
            "error",
            "missing-cursor-skills-discovery",
            discovery_path,
            "Missing .cursor/skills; Cursor Cloud Agents will not discover repository skills.",
        )
        return
    if not discovery_path.is_dir():
        add_issue(
            issues,
            "error",
            "invalid-cursor-skills-discovery",
            discovery_path,
            ".cursor/skills must be a directory or a symlink to the skills root.",
        )
        return

    try:
        discovery_resolved = discovery_path.resolve()
        skills_resolved = skills_root.resolve()
    except OSError as error:
        add_issue(issues, "error", "unresolvable-cursor-skills-discovery", discovery_path, str(error))
        return

    if discovery_resolved != skills_resolved:
        discovered_names = cursor_discovery_skill_names(discovery_path)
        missing = skill_names - discovered_names
        extra = discovered_names - skill_names
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(sorted(missing))}")
            if extra:
                details.append(f"extra {', '.join(sorted(extra))}")
            add_issue(
                issues,
                "error",
                "cursor-skills-discovery-drift",
                discovery_path,
                "`.cursor/skills` does not match the canonical skills root (" + "; ".join(details) + ").",
            )
        for name in sorted(skill_names & discovered_names):
            if tree_digest(discovery_path / name) != tree_digest(skills_root / name):
                add_issue(issues, "error", "cursor-skills-content-drift", discovery_path / name,
                          "Discovery copy differs from the canonical skill content.")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in IGNORED_SUFFIXES or any(part in IGNORED_TREE_PARTS for part in path.parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_profile(skills_root: Path, profile_root: Path, issues: list[Issue]) -> None:
    if not profile_root.is_dir():
        add_issue(issues, "error", "missing-profile-root", profile_root, "Profile root does not exist or is not a directory.")
        return
    repository_skills = {path.name: path for path in skills_root.iterdir() if (path / "SKILL.md").is_file()}
    profile_skills = {
        path.name: path
        for path in profile_root.iterdir()
        if not path.name.startswith(".") and path.is_dir() and (path / "SKILL.md").is_file()
    }
    for name in sorted(repository_skills.keys() - profile_skills.keys()):
        add_issue(issues, "warning", "profile-missing-skill", profile_root, f"Profile is missing repository skill: {name}")
    for name in sorted(profile_skills.keys() - repository_skills.keys()):
        add_issue(issues, "warning", "profile-extra-skill", profile_skills[name], f"Profile contains a skill absent from the repository: {name}")
    for name in sorted(repository_skills.keys() & profile_skills.keys()):
        if tree_digest(repository_skills[name]) != tree_digest(profile_skills[name]):
            add_issue(issues, "warning", "profile-skill-drift", profile_skills[name], f"Profile skill differs from repository: {name}")


def audit_repository(root: Path, profile_root: Path | None = None) -> Audit:
    root = root.expanduser().resolve()
    skills_root = root / "skills" if (root / "skills").is_dir() else root
    issues: list[Issue] = []
    if not skills_root.is_dir():
        add_issue(issues, "error", "missing-skills-root", skills_root, "Could not locate a skills directory.")
        return Audit(root=str(root), skills=0, issues=issues)

    skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())
    for path in sorted(skills_root.iterdir()):
        if path.is_dir() and not path.name.startswith(".") and not (path / "SKILL.md").is_file():
            add_issue(issues, "error", "missing-skill-entrypoint", path, "Skill directory is missing SKILL.md.")
    if not skill_dirs:
        add_issue(issues, "error", "no-skills", skills_root, "No skill folders containing SKILL.md were found.")
    descriptions: dict[str, str] = {}
    for skill_dir in skill_dirs:
        parsed = parse_skill(skill_dir / "SKILL.md", issues)
        if parsed is None:
            continue
        metadata, body = parsed
        skill_name = validate_frontmatter(skill_dir, metadata, body, issues)
        validate_openai_metadata(skill_dir, skill_name, issues)
        validate_resource_references(skill_dir, body, issues)
        validate_python(skill_dir, issues)
        description = metadata.get("description")
        if skill_name and isinstance(description, str):
            descriptions[skill_name] = description

    validate_trigger_overlap(descriptions, skills_root, issues)
    repository_root = root if (root / "skills").is_dir() else root.parent
    skill_names = set(descriptions)
    validate_catalog(repository_root, skill_names, issues)
    if (root / "skills").is_dir():
        validate_cursor_cloud_discovery(repository_root, skills_root, skill_names, issues)
    if profile_root is not None:
        validate_profile(skills_root, profile_root.expanduser().resolve(), issues)
    issues.sort(key=lambda issue: ({"error": 0, "warning": 1}[issue.severity], issue.path, issue.code))
    return Audit(root=str(root), skills=len(skill_dirs), issues=issues)


def print_audit(audit: Audit, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "root": audit.root,
                    "skills": audit.skills,
                    "errors": audit.errors,
                    "warnings": audit.warnings,
                    "issues": [asdict(issue) for issue in audit.issues],
                },
                indent=2,
            )
        )
        return
    for issue in audit.issues:
        print(f"{issue.severity.upper()} [{issue.code}] {issue.path}: {issue.message}")
    print(f"Validated {audit.skills} skills: {audit.errors} error(s), {audit.warnings} warning(s).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd(), help="Repository root or skills directory")
    parser.add_argument("--profile-root", type=Path, help="Optional installed skill root to compare")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Fail when warnings are present")
    arguments = parser.parse_args()
    audit = audit_repository(arguments.root, arguments.profile_root)
    print_audit(audit, arguments.json)
    return 1 if audit.errors or (arguments.strict and audit.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
