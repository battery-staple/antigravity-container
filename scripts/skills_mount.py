#!/usr/bin/env python3
"""
skills_mount.py - Discovers, resolves, and manages read-only mounts for skills.json directories.
"""

import json
import os
import sys
import yaml


def find_skill_config_files(allowed_workspaces: list, global_gemini_dir: str = None) -> list:
    """
    Scans candidate skills.json locations:
    1. Global configuration: ~/.gemini/config/skills.json
    2. Whitelisted workspaces: .agents/skills.json, .agent/skills.json,
       _agents/skills.json, _agent/skills.json, and skills.json in workspace roots.
    """
    config_files = []

    # 1. Global config
    gemini_dir = global_gemini_dir or os.environ.get("HOST_GEMINI_DIR") or os.path.expanduser("~/.gemini")
    global_config = os.path.join(gemini_dir, "config", "skills.json")
    if os.path.isfile(global_config):
        config_files.append(os.path.abspath(global_config))

    # 2. Workspace configs
    workspace_candidates = [
        os.path.join(".agents", "skills.json"),
        os.path.join(".agent", "skills.json"),
        os.path.join("_agents", "skills.json"),
        os.path.join("_agent", "skills.json"),
        "skills.json",
    ]

    for ws in (allowed_workspaces or []):
        if not ws:
            continue
        ws_expanded = os.path.abspath(os.path.expanduser(ws))
        if not os.path.isdir(ws_expanded):
            continue
        for candidate in workspace_candidates:
            target = os.path.join(ws_expanded, candidate)
            if os.path.isfile(target):
                target_abs = os.path.abspath(target)
                if target_abs not in config_files:
                    config_files.append(target_abs)

    return config_files


def parse_skills_configs(config_files: list) -> list:
    """
    Recursively parses JSON configuration files, traversing 'inherits' chains
    with cycle detection. Returns a list of raw entry dicts with source context.
    """
    raw_entries = []
    visited_files = set()

    def _parse_file(file_path: str):
        norm_path = os.path.abspath(file_path)
        if norm_path in visited_files:
            return
        visited_files.add(norm_path)

        if not os.path.isfile(norm_path):
            return

        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Sandbox Warning] Failed to parse skills config {norm_path}: {e}", file=sys.stderr)
            return

        if not isinstance(data, dict):
            return

        base_dir = os.path.dirname(norm_path)

        # Process 'inherits'
        inherits = data.get("inherits", [])
        if isinstance(inherits, list):
            for item in inherits:
                inherit_path = item.get("path") if isinstance(item, dict) else item
                if isinstance(inherit_path, str) and inherit_path.strip():
                    inherit_path = inherit_path.strip()
                    if inherit_path.startswith("~"):
                        resolved_inherit = os.path.expanduser(inherit_path)
                    elif os.path.isabs(inherit_path):
                        resolved_inherit = inherit_path
                    else:
                        resolved_inherit = os.path.join(base_dir, inherit_path)
                    _parse_file(resolved_inherit)

        # Process 'entries'
        entries = data.get("entries", [])
        if isinstance(entries, list):
            for entry in entries:
                entry_path = entry.get("path") if isinstance(entry, dict) else entry
                if isinstance(entry_path, str) and entry_path.strip():
                    raw_entries.append({
                        "path": entry_path.strip(),
                        "base_dir": base_dir,
                        "source_config": norm_path,
                    })

    for cfg in (config_files or []):
        _parse_file(cfg)

    return raw_entries


def resolve_and_validate_skill_paths(raw_entries: list, warn: bool = True) -> list:
    """
    Resolves raw path entries to absolute paths and validates directory existence on the host.
    Logs a warning on missing directories and returns a deduplicated list of valid paths.
    """
    valid_paths = []
    seen = set()

    for entry in (raw_entries or []):
        raw_path = entry["path"]
        base_dir = entry["base_dir"]
        source_config = entry.get("source_config", "unknown")

        if raw_path.startswith("~"):
            resolved = os.path.abspath(os.path.expanduser(raw_path))
        elif os.path.isabs(raw_path):
            resolved = os.path.abspath(raw_path)
        else:
            resolved = os.path.abspath(os.path.join(base_dir, raw_path))

        # Normalize trailing slash
        resolved = resolved.rstrip("/")

        if resolved in seen:
            continue
        seen.add(resolved)

        if os.path.isdir(resolved):
            valid_paths.append(resolved)
        else:
            if warn:
                print(
                    f"[Sandbox Warning] Skill directory not found on host: {resolved} (referenced in {source_config})",
                    file=sys.stderr,
                )

    return valid_paths


def resolve_mount_conflicts(skill_paths: list, workspace_paths: list) -> list:
    """
    Resolves mount conflicts and deduplicates paths:
    1. Skips skill paths that are identical to or inside an active workspace mount.
    2. Deduplicates nested skill paths (keeping only the top-level parent).
    3. Retains skill paths that are ancestors of a workspace.
    """
    normalized_ws = [os.path.abspath(w).rstrip("/") for w in (workspace_paths or []) if w]

    # Step 1: Filter out skill paths covered by a workspace
    uncovered_skills = []
    for s in (skill_paths or []):
        norm_s = os.path.abspath(s).rstrip("/")
        # Check if identical to workspace or inside a workspace
        is_covered = any(norm_s == w or norm_s.startswith(w + "/") for w in normalized_ws)
        if not is_covered:
            uncovered_skills.append(norm_s)

    # Step 2: Deduplicate nested skill paths among themselves (keep ancestor)
    # Sort by path length ascending so parents come before children
    uncovered_skills.sort(key=lambda p: (len(p.split("/")), p))
    final_skills = []
    for s in uncovered_skills:
        # If 's' is a child of an already included skill path, skip it
        if any(s.startswith(parent + "/") for parent in final_skills):
            continue
        final_skills.append(s)

    return final_skills


def build_compose_volume_entries(skill_paths: list, workspace_paths: list) -> list:
    """
    Generates Docker Compose volume entries with :ro and :cached flags.
    Sorts hierarchically (by path depth) so parent directories are mounted
    before child submounts (ensuring child :cached mounts overlay parent :ro mounts).
    """
    mount_items = []

    for s in (skill_paths or []):
        norm_s = os.path.abspath(s).rstrip("/")
        mount_items.append({
            "path": norm_s,
            "line": f'      - "{norm_s}:{norm_s}:ro"',
        })

    for w in (workspace_paths or []):
        norm_w = os.path.abspath(w).rstrip("/")
        mount_items.append({
            "path": norm_w,
            "line": f'      - "{norm_w}:{norm_w}:cached"',
        })

    # Sort hierarchically: shorter path component count first, then alphabetical
    mount_items.sort(key=lambda item: (len(item["path"].split("/")), item["path"]))

    return [item["line"] for item in mount_items]


def generate_compose_override_content(whitelist_file: str, global_gemini_dir: str = None, warn: bool = True) -> str:
    """
    Executes the full pipeline and generates the content for docker-compose.override.yml.
    Returns an empty string if there are no volume mounts to write.
    """
    if not os.path.isfile(whitelist_file):
        return ""

    try:
        with open(whitelist_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        if warn:
            print(f"[Sandbox Warning] Failed to read whitelist file {whitelist_file}: {e}", file=sys.stderr)
        return ""

    raw_workspaces = data.get("allowed_workspaces", [])
    valid_workspaces = [
        os.path.abspath(os.path.expanduser(w)).rstrip("/")
        for w in raw_workspaces
        if w and os.path.isdir(os.path.expanduser(w))
    ]

    # Pipeline
    config_files = find_skill_config_files(valid_workspaces, global_gemini_dir)
    raw_entries = parse_skills_configs(config_files)
    valid_skill_paths = resolve_and_validate_skill_paths(raw_entries, warn=warn)
    final_skill_paths = resolve_mount_conflicts(valid_skill_paths, valid_workspaces)
    volume_lines = build_compose_volume_entries(final_skill_paths, valid_workspaces)

    if not volume_lines:
        return ""

    lines = [
        "# Auto-generated by antigravity-sandbox CLI. Do not edit manually.",
        "services:",
        "  antigravity-sandbox:",
        "    volumes:",
    ]
    lines.extend(volume_lines)
    return "\n".join(lines) + "\n"


def get_discovered_skills_summary(whitelist_file: str, global_gemini_dir: str = None) -> dict:
    """
    Returns a dictionary summarizing discovered skills for CLI display.
    """
    workspaces = []
    if os.path.isfile(whitelist_file):
        try:
            with open(whitelist_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                workspaces = [
                    os.path.abspath(os.path.expanduser(w)).rstrip("/")
                    for w in data.get("allowed_workspaces", [])
                    if w and os.path.isdir(os.path.expanduser(w))
                ]
        except Exception:
            pass

    config_files = find_skill_config_files(workspaces, global_gemini_dir)
    raw_entries = parse_skills_configs(config_files)
    valid_skills = resolve_and_validate_skill_paths(raw_entries, warn=False)
    mounted_skills = resolve_mount_conflicts(valid_skills, workspaces)

    return {
        "config_files": config_files,
        "valid_skills": valid_skills,
        "mounted_skills": mounted_skills,
        "workspaces": workspaces,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Antigravity Sandbox Skills Mount Generator")
    parser.add_argument("--whitelist", default=os.path.expanduser("~/.antigravity-sandbox/whitelist.yaml"), help="Path to whitelist.yaml")
    parser.add_argument("--override-file", default=os.path.expanduser("~/.antigravity-sandbox/docker-compose.override.yml"), help="Path to docker-compose.override.yml")
    parser.add_argument("--gemini-dir", default=None, help="Path to host .gemini directory")
    parser.add_argument("--generate", action="store_true", help="Generate docker-compose.override.yml")
    parser.add_argument("--list", action="store_true", help="List discovered and mounted skills")

    args = parser.parse_args()

    if args.list:
        summary = get_discovered_skills_summary(args.whitelist, args.gemini_dir)
        print("==========================================================")
        print("  Discovered Skills Configs & Mounts")
        print("==========================================================")
        print(f"Config files scanned ({len(summary['config_files'])}):")
        for cf in summary["config_files"]:
            print(f"  - {cf}")
        print(f"\nMounted read-only skill directories ({len(summary['mounted_skills'])}):")
        if not summary["mounted_skills"]:
            print("  (No external read-only skill directories mounted)")
        for s in summary["mounted_skills"]:
            print(f"  - {s} [read-only]")
        print("==========================================================")
    elif args.generate:
        content = generate_compose_override_content(args.whitelist, args.gemini_dir, warn=True)
        if not content:
            if os.path.exists(args.override_file):
                os.remove(args.override_file)
                print(f"[Sandbox] Removed empty override file: {args.override_file}")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(args.override_file)), exist_ok=True)
            with open(args.override_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[Sandbox] Updated override file: {args.override_file}")
