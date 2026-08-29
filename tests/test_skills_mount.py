#!/usr/bin/env python3
"""
Unit tests for scripts/skills_mount.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import yaml

# Add scripts directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, os.path.join(REPO_DIR, "scripts"))

from skills_mount import (
    find_skill_config_files,
    parse_skills_configs,
    resolve_and_validate_skill_paths,
    resolve_mount_conflicts,
    build_compose_volume_entries,
    generate_compose_override_content,
    get_discovered_skills_summary,
)


class TestSkillsMount(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_skills_mount_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_skill_config_files(self):
        # Setup fake global config
        fake_gemini = os.path.join(self.temp_dir, "gemini")
        os.makedirs(os.path.join(fake_gemini, "config"), exist_ok=True)
        global_skills = os.path.join(fake_gemini, "config", "skills.json")
        with open(global_skills, "w") as f:
            f.write("{}")

        # Setup fake workspaces
        ws1 = os.path.join(self.temp_dir, "ws1")
        os.makedirs(os.path.join(ws1, ".agents"), exist_ok=True)
        ws1_skills = os.path.join(ws1, ".agents", "skills.json")
        with open(ws1_skills, "w") as f:
            f.write("{}")

        ws2 = os.path.join(self.temp_dir, "ws2")
        os.makedirs(os.path.join(ws2, "_agents"), exist_ok=True)
        ws2_skills = os.path.join(ws2, "_agents", "skills.json")
        with open(ws2_skills, "w") as f:
            f.write("{}")

        ws3_empty = os.path.join(self.temp_dir, "ws3")
        os.makedirs(ws3_empty, exist_ok=True)

        found = find_skill_config_files([ws1, ws2, ws3_empty, "/non/existent"], global_gemini_dir=fake_gemini)
        self.assertEqual(len(found), 3)
        self.assertIn(os.path.abspath(global_skills), found)
        self.assertIn(os.path.abspath(ws1_skills), found)
        self.assertIn(os.path.abspath(ws2_skills), found)

    def test_parse_skills_configs_and_circular_inherits(self):
        # Create config A which inherits from B, and B inherits from A (cycle)
        cfg_a = os.path.join(self.temp_dir, "skills_a.json")
        cfg_b = os.path.join(self.temp_dir, "skills_b.json")

        with open(cfg_a, "w") as f:
            json.dump({
                "inherits": [{"path": "skills_b.json"}],
                "entries": [{"path": "dir_a"}]
            }, f)

        with open(cfg_b, "w") as f:
            json.dump({
                "inherits": [{"path": "skills_a.json"}],
                "entries": [{"path": "dir_b"}]
            }, f)

        entries = parse_skills_configs([cfg_a])
        self.assertEqual(len(entries), 2)
        paths = [e["path"] for e in entries]
        self.assertIn("dir_a", paths)
        self.assertIn("dir_b", paths)

    def test_resolve_and_validate_skill_paths(self):
        # Create valid directories
        valid_dir1 = os.path.join(self.temp_dir, "skill1")
        valid_dir2 = os.path.join(self.temp_dir, "sub", "skill2")
        os.makedirs(valid_dir1, exist_ok=True)
        os.makedirs(valid_dir2, exist_ok=True)

        raw_entries = [
            {"path": valid_dir1, "base_dir": self.temp_dir, "source_config": "cfg1"},
            {"path": "sub/skill2", "base_dir": self.temp_dir, "source_config": "cfg1"},
            {"path": "non_existent_dir", "base_dir": self.temp_dir, "source_config": "cfg1"},
            {"path": valid_dir1, "base_dir": self.temp_dir, "source_config": "cfg2"}, # Duplicate
        ]

        valid = resolve_and_validate_skill_paths(raw_entries, warn=False)
        self.assertEqual(len(valid), 2)
        self.assertIn(os.path.abspath(valid_dir1), valid)
        self.assertIn(os.path.abspath(valid_dir2), valid)

    def test_resolve_mount_conflicts(self):
        ws_root = os.path.join(self.temp_dir, "workspace")
        ws_sub = os.path.join(ws_root, "subproject")
        os.makedirs(ws_sub, exist_ok=True)

        # 1. Skill identical to workspace -> should be omitted
        skill_exact = ws_root
        # 2. Skill inside workspace -> should be omitted
        skill_inside = os.path.join(ws_root, "skills")
        # 3. Nested skills -> outer skill should be kept, inner dropped
        skill_parent = os.path.join(self.temp_dir, "skills_root")
        skill_child = os.path.join(skill_parent, "extra_skills")
        # 4. Skill is an ancestor of a workspace -> skill should be kept
        ancestor_skill = self.temp_dir
        ws_nested = os.path.join(ancestor_skill, "nested_ws")

        # Case A: Standard deduplication
        skills = [skill_exact, skill_inside, skill_parent, skill_child]
        workspaces = [ws_root]
        resolved = resolve_mount_conflicts(skills, workspaces)
        self.assertEqual(resolved, [os.path.abspath(skill_parent)])

        # Case B: Ancestor skill containing workspace
        skills_b = [ancestor_skill]
        workspaces_b = [ws_nested]
        resolved_b = resolve_mount_conflicts(skills_b, workspaces_b)
        self.assertEqual(resolved_b, [os.path.abspath(ancestor_skill)])

    def test_build_compose_volume_entries_ordering(self):
        ancestor_skill = "/Users/dev/all_skills"
        child_ws = "/Users/dev/all_skills/my_workspace"
        other_skill = "/opt/custom_skills"

        volumes = build_compose_volume_entries([ancestor_skill, other_skill], [child_ws])
        
        # Verify formats
        self.assertIn('      - "/Users/dev/all_skills:/Users/dev/all_skills:ro"', volumes)
        self.assertIn('      - "/opt/custom_skills:/opt/custom_skills:ro"', volumes)
        self.assertIn('      - "/Users/dev/all_skills/my_workspace:/Users/dev/all_skills/my_workspace:cached"', volumes)

        # Verify ancestor appears before child in volume list
        idx_parent = volumes.index('      - "/Users/dev/all_skills:/Users/dev/all_skills:ro"')
        idx_child = volumes.index('      - "/Users/dev/all_skills/my_workspace:/Users/dev/all_skills/my_workspace:cached"')
        self.assertLess(idx_parent, idx_child)

    def test_generate_compose_override_end_to_end(self):
        whitelist_yaml = os.path.join(self.temp_dir, "whitelist.yaml")
        fake_gemini = os.path.join(self.temp_dir, "gemini")
        os.makedirs(os.path.join(fake_gemini, "config"), exist_ok=True)

        ws_dir = os.path.join(self.temp_dir, "my_workspace")
        skills_dir = os.path.join(self.temp_dir, "my_skills")
        os.makedirs(ws_dir, exist_ok=True)
        os.makedirs(skills_dir, exist_ok=True)

        with open(os.path.join(fake_gemini, "config", "skills.json"), "w") as f:
            json.dump({"entries": [{"path": skills_dir}]}, f)

        with open(whitelist_yaml, "w") as f:
            yaml.dump({"allowed_workspaces": [ws_dir]}, f)

        content = generate_compose_override_content(whitelist_yaml, global_gemini_dir=fake_gemini, warn=False)
        self.assertIn("services:", content)
        self.assertIn(f'      - "{skills_dir}:{skills_dir}:ro"', content)
        self.assertIn(f'      - "{ws_dir}:{ws_dir}:cached"', content)


if __name__ == "__main__":
    unittest.main()
