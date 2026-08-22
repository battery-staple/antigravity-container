#!/bin/bash
set -e

echo "=========================================================="
echo "  Starting Antigravity Sandboxed Runtime Container"
echo "  Published Port  : 58432 (127.0.0.1)"
echo "  Workspace Mount : /workspace"
echo "=========================================================="

# Ensure permissions on persistent directories
sudo chown $(id -u):$(id -g) /home/developer/.gemini/config/rules 2>/dev/null || sudo chmod 1777 /home/developer/.gemini/config/rules 2>/dev/null || true
export TMPDIR="${TMPDIR:-/home/developer/.gemini/sandbox-tmp}"
mkdir -p /home/developer/.gemini/antigravity "$TMPDIR" /home/developer/.gemini/config /home/developer/.npm-global /home/developer/.gradle /workspace 2>/dev/null || true

# Auto-seed agent customizations (container awareness rule and host-exec skill)
if [ -d "/etc/antigravity/customizations" ] || [ -d "/etc/antigravity/host-rules" ] || [ -d "/etc/antigravity/user-sandbox-rules" ]; then
    # Prepare container rules directory in tmpfs (isolated in RAM, never writes back to host)
    mkdir -p /home/developer/.gemini/config/rules 2>/dev/null || true

    # Validate collisions and merge rules from active sources into tmpfs
    python3 -c "
import os, sys, shutil

rule_sources = [
    ('Host Rules (/etc/antigravity/host-rules)', '/etc/antigravity/host-rules'),
    ('Built-in Rules (/etc/antigravity/customizations/rules)', '/etc/antigravity/customizations/rules'),
    ('User Sandbox Rules (/etc/antigravity/user-sandbox-rules)', '/etc/antigravity/user-sandbox-rules'),
]

rules_dest = '/home/developer/.gemini/config/rules'
seen_files = {}
collisions = {}
valid_files = []

for label, src_dir in rule_sources:
    if not os.path.isdir(src_dir):
        continue
    try:
        entries = sorted(os.listdir(src_dir))
    except Exception as e:
        print(f'[Sandbox Warning] Failed to read rule directory {src_dir}: {e}', file=sys.stderr)
        continue

    for entry in entries:
        if entry.startswith('.'):
            continue
        if not entry.lower().endswith('.md'):
            continue
        src_path = os.path.join(src_dir, entry)
        if not os.path.isfile(src_path):
            continue

        key = entry
        if key in seen_files:
            if key not in collisions:
                collisions[key] = [seen_files[key]]
            collisions[key].append((label, src_path))
        else:
            seen_files[key] = (label, src_path)
            valid_files.append((src_path, os.path.join(rules_dest, entry)))

if collisions:
    print('==========================================================', file=sys.stderr)
    print('  [Sandbox Error] Rule Filename Collision Detected!', file=sys.stderr)
    print('==========================================================', file=sys.stderr)
    print('Conflicting rule files found across configuration sources:', file=sys.stderr)
    for fname, sources in collisions.items():
        print(f'  - \"{fname}\":', file=sys.stderr)
        for lbl, pth in sources:
            print(f'      * {lbl}: {pth}', file=sys.stderr)
    print('', file=sys.stderr)
    print('[Sandbox Error] Refusing to launch sandbox runtime due to ambiguous rule definitions.', file=sys.stderr)
    print('[Sandbox Error] Please ensure all rule filenames are unique across host rules and customizations.', file=sys.stderr)
    print('==========================================================', file=sys.stderr)
    sys.exit(1)

os.makedirs(rules_dest, exist_ok=True)
for src_p, dst_p in valid_files:
    try:
        shutil.copyfile(src_p, dst_p)
    except Exception as e:
        print(f'[Sandbox Error] Failed to copy rule {src_p} -> {dst_p}: {e}', file=sys.stderr)
        sys.exit(1)
"

    # Seed host-exec skill into builtin skills
    mkdir -p /home/developer/.gemini/antigravity/builtin/skills/host-exec /home/developer/.gemini/config/skills/host-exec 2>/dev/null || true
    if [ -f "/etc/antigravity/customizations/skills/host-exec/SKILL.md" ]; then
        cp -u /etc/antigravity/customizations/skills/host-exec/SKILL.md /home/developer/.gemini/antigravity/builtin/skills/host-exec/ 2>/dev/null || \
        cp /etc/antigravity/customizations/skills/host-exec/SKILL.md /home/developer/.gemini/antigravity/builtin/skills/host-exec/ 2>/dev/null || true
    fi
fi

if [ "$#" -eq 0 ]; then
    echo "[Runtime] Launching Antigravity Language Server Daemon..."
    echo "[Runtime] Bridging port 58432 (0.0.0.0) -> language_server (127.0.0.1:58431)..."
    socat TCP-LISTEN:58432,fork,bind=0.0.0.0,reuseaddr TCP:127.0.0.1:58431 2>/dev/null &
    
    echo "[Runtime] Executing Language Server: /usr/local/bin/language_server"
    exec /usr/local/bin/language_server \
        --standalone \
        --override_ide_name antigravity \
        --subclient_type hub \
        --override_ide_version 2.8.1 \
        --override_user_agent_name antigravity \
        --https_server_port 58431 \
        --csrf_token "${CSRF_TOKEN:-antigravity-secure-token}" \
        --app_data_dir antigravity \
        --api_server_url https://generativelanguage.googleapis.com \
        --cloud_code_endpoint https://daily-cloudcode-pa.googleapis.com
else
    exec "$@"
fi
