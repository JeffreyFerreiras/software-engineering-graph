#!/usr/bin/env python3
"""Inventory and conservative copy helper for profile-level agent skills."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


INTERESTING_SUFFIXES = {
    ".md",
    ".mdc",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
}

AI_SKILLS_DEFAULT_REPO_URL = "https://github.com/JeffreyFerreiras/ai-skills.git"

REPO_SKILL_RELATIVE_LOCATIONS = (
    Path(".cursor/skills"),
    Path(".agents/skills"),
    Path(".codex/skills"),
    Path(".claude/skills"),
    Path(".github/skills"),
    Path("skills"),
)

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "cache",
    "cacheddata",
    "code cache",
    "crashpad",
    "gpucache",
    "history",
    "logs",
    "network",
    "node_modules",
    "service worker",
    "session storage",
    "sessions",
    "userstorage",
    "workspace storage",
    "workspacestorage",
}


def home() -> Path:
    return Path.home()


def default_roots() -> dict[str, Path]:
    codex_home = os.environ.get("CODEX_HOME")
    appdata = os.environ.get("APPDATA")
    roots = {
        "codex-skills": Path(codex_home).expanduser() / "skills" if codex_home else home() / ".codex" / "skills",
        "claude": home() / ".claude",
        "cursor-home": home() / ".cursor",
    }
    if appdata:
        roots["cursor-user"] = Path(appdata) / "Cursor" / "User"
        roots["vscode-user"] = Path(appdata) / "Code" / "User"
    return roots


def vscode_user_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Code" / "User" / "settings.json"
    return home() / "AppData" / "Roaming" / "Code" / "User" / "settings.json"


def parse_root(value: str) -> tuple[str, Path]:
    if "=" not in value:
        path = Path(value).expanduser()
        return path.name or str(path), path
    name, raw_path = value.split("=", 1)
    if not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("--root must be NAME=PATH or PATH")
    return name.strip(), Path(raw_path).expanduser()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_interesting_files(
    root: Path,
    max_depth: int | None = None,
    max_files: int | None = None,
    excluded_dirs: set[str] | None = None,
) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    count = 0
    excluded_dirs = excluded_dirs or set()
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        dirnames[:] = [name for name in dirnames if name.lower() not in excluded_dirs]
        if max_depth is not None:
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= max_depth:
                dirnames[:] = []
            if depth > max_depth:
                continue
        for filename in filenames:
            path = current_path / filename
            if path.suffix.lower() not in INTERESTING_SUFFIXES:
                continue
            yield path
            count += 1
            if max_files is not None and count >= max_files:
                return


def inventory_roots(
    roots: dict[str, Path],
    max_depth: int | None,
    max_files: int | None,
    excluded_dirs: set[str],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for name, root in roots.items():
        root = root.expanduser()
        record: dict[str, object] = {
            "name": name,
            "path": str(root),
            "exists": root.exists(),
            "type": "missing",
            "files": [],
        }
        if root.is_file():
            record["type"] = "file"
        elif root.is_dir():
            record["type"] = "directory"
        if root.exists():
            files = []
            for path in iter_interesting_files(
                root,
                max_depth=max_depth,
                max_files=max_files,
                excluded_dirs=excluded_dirs,
            ):
                try:
                    stat = path.stat()
                    files.append(
                        {
                            "path": str(path),
                            "relative_path": str(path.relative_to(root)) if root.is_dir() else path.name,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                            "sha256": sha256_file(path),
                        }
                    )
                except OSError as exc:
                    files.append({"path": str(path), "error": str(exc)})
            record["files"] = files
        records.append(record)
    return records


def print_inventory(records: list[dict[str, object]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(records, indent=2))
        return
    for record in records:
        print(f"{record['name']}: {record['path']} [{record['type']}]")
        files = record.get("files", [])
        if not files:
            continue
        for item in files:
            if "error" in item:
                print(f"  ! {item['path']}: {item['error']}")
            else:
                print(f"  - {item['relative_path']} ({item['size']} bytes, {item['modified']})")


def paths_identical(source: Path, target: Path) -> bool:
    if source.is_file() and target.is_file():
        return sha256_file(source) == sha256_file(target)
    if source.is_dir() and target.is_dir():
        comparison = filecmp.dircmp(source, target)
        if comparison.left_only or comparison.right_only or comparison.funny_files:
            return False
        # filecmp.dircmp only compares os.stat() signatures by default.
        # Check actual contents for differing files or subdirectories:
        for common_file in comparison.common_files:
            if sha256_file(source / common_file) != sha256_file(target / common_file):
                return False
        return all(paths_identical(source / child, target / child) for child in comparison.common_dirs)
    return False


def backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = target.parent / ".sync-agent-skills-backups"
    return backup_dir / f"{target.name}.{stamp}"


def find_installed_repo_skill_roots(
    repo_root: Path,
    candidates: Iterable[Path] = REPO_SKILL_RELATIVE_LOCATIONS,
) -> list[Path]:
    """Return directories in repo_root that contain installed skill folders."""
    discovered: list[Path] = []
    seen_real_paths: set[Path] = set()
    for rel_path in candidates:
        candidate = (repo_root / rel_path)
        if not candidate.is_dir():
            continue
        # Avoid treating canonical skills/ as an installed target if repo_root IS the master skills repo
        # when running in the skills repo itself, unless it's explicitly an installed target.
        has_skills = any(
            item.is_dir() and (item / "SKILL.md").is_file()
            for item in candidate.iterdir()
        )
        if has_skills:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved not in seen_real_paths:
                seen_real_paths.add(resolved)
                discovered.append(candidate)
    return discovered


def list_skills_in_root(root: Path) -> dict[str, Path]:
    """Map skill name to its directory inside root."""
    skills: dict[str, Path] = {}
    if not root.is_dir():
        return skills
    for item in root.iterdir():
        if item.is_dir() and not item.name.startswith(".") and (item / "SKILL.md").is_file():
            skills[item.name] = item
    return skills


def sync_skills_from_master(
    master_skills_dir: Path,
    target_root: Path,
    apply: bool = False,
    force: bool = False,
    skill_names: Iterable[str] | None = None,
    only_existing: bool = True,
) -> list[dict[str, object]]:
    """Update skills in target_root from master_skills_dir."""
    master_skills = list_skills_in_root(master_skills_dir)
    target_skills = list_skills_in_root(target_root)
    results: list[dict[str, object]] = []

    names_to_sync = (
        set(skill_names)
        if skill_names is not None
        else (set(target_skills.keys()) if only_existing else set(master_skills.keys()))
    )

    for name in sorted(names_to_sync):
        if name not in master_skills:
            results.append(
                {
                    "skill": name,
                    "source": None,
                    "target": str(target_root / name),
                    "apply": apply,
                    "changed": False,
                    "actions": [f"skill '{name}' not found in master skills repository"],
                }
            )
            continue

        source_path = master_skills[name]
        copy_res = copy_source(
            source=source_path,
            target_root=target_root,
            target_name=name,
            apply=apply,
            force=force,
        )
        copy_res["skill"] = name
        results.append(copy_res)

    return results


def copy_source(source: Path, target_root: Path, target_name: str | None, apply: bool, force: bool) -> dict[str, object]:
    source = source.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    target = target_root / (target_name or source.name)
    result: dict[str, object] = {
        "source": str(source),
        "target": str(target),
        "apply": apply,
        "changed": False,
        "actions": [],
    }

    if not source.exists():
        raise FileNotFoundError(f"source does not exist: {source}")
    if not target_root.exists():
        result["actions"].append(f"create directory {target_root}")
        if apply:
            target_root.mkdir(parents=True, exist_ok=True)
    if target.exists() and paths_identical(source, target):
        result["actions"].append("target already matches source")
        return result
    if target.exists():
        if not force:
            result["actions"].append("target differs; rerun with --force to replace with backup")
            return result
        backup = backup_path(target)
        result["actions"].append(f"backup {target} to {backup}")
        if apply:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup))
    result["actions"].append(f"copy {source} to {target}")
    result["changed"] = True
    if apply:
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return result


def strip_json_comments(text: str) -> str:
    """Remove JSON line and block comments while preserving quoted strings."""
    result: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            result.append(character)
            index += 1
            continue
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if character == "/" and next_character == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and next_character == "*":
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            index = min(index + 2, len(text))
            continue
        result.append(character)
        index += 1
    return "".join(result)


def strip_trailing_commas(text: str) -> str:
    """Remove trailing JSON commas while preserving quoted strings."""
    result: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            result.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        result.append(character)
        index += 1
    return "".join(result)


def load_json_object(path: Path) -> tuple[dict[str, object], bool]:
    if not path.exists():
        return {}, False
    raw = path.read_text(encoding="utf-8")
    is_jsonc = False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(strip_trailing_commas(strip_json_comments(raw)))
        is_jsonc = True
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data, is_jsonc


def write_json_object(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = backup_path(path)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")


def doctor_vscode(settings_path: Path | None, apply: bool) -> dict[str, object]:
    settings_path = (settings_path or vscode_user_settings_path()).expanduser()
    settings_exists = settings_path.exists()
    settings, settings_is_jsonc = load_json_object(settings_path)
    locations = settings.get("chat.agentSkillsLocations")
    if not isinstance(locations, dict):
        locations = {}

    desired = dict(settings)
    desired["chat.useAgentSkills"] = True
    desired["github.copilot.chat.skillTool.enabled"] = True
    desired["chat.agentSkillsLocations"] = {**locations, "~/.codex/skills": True}

    issues = []
    if not shutil.which("code"):
        issues.append("VS Code CLI 'code' is not on PATH")
    if settings.get("chat.useAgentSkills") is not True:
        issues.append("chat.useAgentSkills is not true")
    if settings.get("github.copilot.chat.skillTool.enabled") is not True:
        issues.append("github.copilot.chat.skillTool.enabled is not true")
    if locations.get("~/.codex/skills") is not True:
        issues.append("chat.agentSkillsLocations does not include ~/.codex/skills")

    changed = desired != settings
    actions = []
    if changed:
        actions.append(f"update {settings_path}")
        if settings_exists:
            actions.append(f"backup existing settings beside {settings_path}")
        if settings_is_jsonc:
            actions.append("preserve JSONC comments and trailing commas with a manual or JSONC-aware edit")
        if apply:
            if settings_is_jsonc:
                raise ValueError(
                    f"refusing to rewrite JSONC settings as strict JSON: {settings_path}; "
                    "apply the reported settings with a JSONC-aware editor"
                )
            write_json_object(settings_path, desired)
    else:
        actions.append("VS Code agent skill settings already include ~/.codex/skills")

    return {
        "settings_path": str(settings_path),
        "settings_exists": settings_exists,
        "settings_is_jsonc": settings_is_jsonc,
        "code_cli_found": shutil.which("code") is not None,
        "issues": issues,
        "apply": apply,
        "changed": changed,
        "actions": actions,
        "effective_agent_skills_locations": desired["chat.agentSkillsLocations"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory", help="Inventory profile-level agent files")
    inventory_parser.add_argument("--root", action="append", type=parse_root, help="Additional or replacement root as NAME=PATH")
    inventory_parser.add_argument("--json", action="store_true", help="Print JSON")
    inventory_parser.add_argument("--max-depth", type=int, default=5, help="Maximum directory depth to scan; default: 5")
    inventory_parser.add_argument("--max-files", type=int, default=500, help="Maximum matching files per root; default: 500")
    inventory_parser.add_argument(
        "--include-noisy-dirs",
        action="store_true",
        help="Include cache/history/storage directories that are skipped by default",
    )

    sync_parser = subparsers.add_parser("sync", help="Copy a source file or folder into a target root")
    sync_parser.add_argument("--source", required=True, type=Path)
    sync_parser.add_argument("--target-root", required=True, type=Path)
    sync_parser.add_argument("--target-name", help="Override target file or folder name")
    sync_parser.add_argument("--apply", action="store_true", help="Perform changes; default is dry-run")
    sync_parser.add_argument("--force", action="store_true", help="Replace differing target after backing it up")
    sync_parser.add_argument("--json", action="store_true", help="Print JSON")

    vscode_parser = subparsers.add_parser("doctor-vscode", help="Check VS Code agent skill discovery settings")
    vscode_parser.add_argument("--settings", type=Path, help="Path to VS Code settings.json; default is user profile")
    vscode_parser.add_argument("--apply", action="store_true", help="Update settings.json after backing it up")
    vscode_parser.add_argument("--json", action="store_true", help="Print JSON")

    sync_from_master_parser = subparsers.add_parser(
        "sync-from-master",
        help="Update installed skills in a local repo or profile from master skills repository",
    )
    sync_from_master_parser.add_argument(
        "--master",
        type=Path,
        required=True,
        help="Path to master skills repository (checkout of ai-skills)",
    )
    sync_from_master_parser.add_argument(
        "--target-root",
        type=Path,
        action="append",
        help="Specific target skill directory to update (can be specified multiple times)",
    )
    sync_from_master_parser.add_argument(
        "--target-repo",
        type=Path,
        help="Target repository to scan for installed skills (e.g. .cursor/skills, .codex/skills, etc.)",
    )
    sync_from_master_parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Specific skill name(s) to sync (default: sync all installed or existing skills in target)",
    )
    sync_from_master_parser.add_argument(
        "--all",
        action="store_true",
        help="Install all master skills, not just currently existing skills in target",
    )
    sync_from_master_parser.add_argument("--apply", action="store_true", help="Perform changes; default is dry-run")
    sync_from_master_parser.add_argument("--force", action="store_true", help="Replace differing target after backing it up")
    sync_from_master_parser.add_argument("--json", action="store_true", help="Print JSON")

    args = parser.parse_args()
    if args.command == "inventory":
        roots = dict(args.root) if args.root else default_roots()
        excluded_dirs = set() if args.include_noisy_dirs else DEFAULT_EXCLUDED_DIRS
        records = inventory_roots(roots, max_depth=args.max_depth, max_files=args.max_files, excluded_dirs=excluded_dirs)
        print_inventory(records, args.json)
        return 0

    if args.command == "sync":
        result = copy_source(args.source, args.target_root, args.target_name, args.apply, args.force)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for action in result["actions"]:
                prefix = "would " if not args.apply and not action.startswith("target already") else ""
                print(prefix + action)
        return 0

    if args.command == "doctor-vscode":
        result = doctor_vscode(args.settings, args.apply)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"settings: {result['settings_path']}")
            print(f"code CLI found: {result['code_cli_found']}")
            if result["issues"]:
                print("issues:")
                for issue in result["issues"]:
                    print(f"  - {issue}")
            else:
                print("issues: none")
            for action in result["actions"]:
                prefix = "" if args.apply or action.startswith("VS Code") else "would "
                print(prefix + action)
        return 0

    if args.command == "sync-from-master":
        master_path = args.master.expanduser().resolve()
        master_skills_dir = master_path / "skills" if (master_path / "skills").is_dir() else master_path
        if not master_skills_dir.is_dir():
            raise FileNotFoundError(f"master skills directory not found at {master_skills_dir}")

        target_roots: list[Path] = []
        if args.target_root:
            target_roots.extend(p.expanduser().resolve() for p in args.target_root)
        if args.target_repo:
            repo_path = args.target_repo.expanduser().resolve()
            installed = find_installed_repo_skill_roots(repo_path)
            target_roots.extend(installed)

        if not target_roots:
            print("No target roots specified or found in target repository.")
            return 1

        all_results: list[dict[str, object]] = []
        for target_root in target_roots:
            res = sync_skills_from_master(
                master_skills_dir=master_skills_dir,
                target_root=target_root,
                apply=args.apply,
                force=args.force,
                skill_names=args.skills,
                only_existing=not args.all,
            )
            all_results.extend(res)

        if args.json:
            print(json.dumps(all_results, indent=2))
        else:
            for item in all_results:
                skill_name = item.get("skill", "")
                actions = item.get("actions", [])
                target = item.get("target", "")
                print(f"Skill '{skill_name}' -> {target}:")
                for action in actions:
                    prefix = "would " if not args.apply and not str(action).startswith("target already") and not str(action).startswith("skill '") else ""
                    print(f"  {prefix}{action}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
