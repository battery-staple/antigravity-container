#!/bin/bash
set -e

echo "=========================================================="
echo "  Starting Antigravity Sandboxed Runtime Container"
echo "  Published Port  : 58432 (127.0.0.1)"
echo "  Workspace Mount : /workspace"
echo "=========================================================="

# Ensure permissions on persistent directories
sudo chown $(id -u):$(id -g) /home/developer/.gemini/config/rules 2>/dev/null || sudo chmod 1777 /home/developer/.gemini/config/rules 2>/dev/null || true
mkdir -p /home/developer/.gemini/antigravity /home/developer/.gemini/config /home/developer/.npm-global /home/developer/.gradle /workspace 2>/dev/null || true

# Auto-seed agent customizations (container awareness rule and host-exec skill)
if [ -d "/etc/antigravity/customizations" ]; then
    # Prepare container rules directory in tmpfs (isolated in RAM, never writes back to host)
    mkdir -p /home/developer/.gemini/config/rules 2>/dev/null || true

    # 1. Inherit all host rules from read-only staging mount
    if [ -d "/etc/antigravity/host-rules" ]; then
        cp -r /etc/antigravity/host-rules/. /home/developer/.gemini/config/rules/ 2>/dev/null || true
    fi

    # 2. Inject container environment rule into tmpfs rules
    if [ -f "/etc/antigravity/customizations/rules/container-environment.md" ]; then
        cp /etc/antigravity/customizations/rules/container-environment.md /home/developer/.gemini/config/rules/ 2>/dev/null || true
    fi

    # Seed host-exec skill into builtin skills
    mkdir -p /home/developer/.gemini/antigravity/builtin/skills/host-exec /home/developer/.gemini/config/skills/host-exec 2>/dev/null || true
    if [ -f "/etc/antigravity/customizations/skills/host-exec/SKILL.md" ]; then
        cp -u /etc/antigravity/customizations/skills/host-exec/SKILL.md /home/developer/.gemini/antigravity/builtin/skills/host-exec/ 2>/dev/null || \
        cp /etc/antigravity/customizations/skills/host-exec/SKILL.md /home/developer/.gemini/antigravity/builtin/skills/host-exec/ 2>/dev/null || true
    fi
fi

if [ "$#" -eq 0 ]; then
    echo "[Runtime] Launching Antigravity Language Server Daemon..."
    echo "[Runtime] Bridging port 58432 (0.0.0.0) -> language_server (127.0.0.1:58433)..."
    socat TCP-LISTEN:58432,fork,bind=0.0.0.0,reuseaddr TCP:127.0.0.1:58433 2>/dev/null &
    
    echo "[Runtime] Executing Language Server: /usr/local/bin/language_server"
    exec /usr/local/bin/language_server \
        --standalone \
        --override_ide_name antigravity \
        --subclient_type hub \
        --override_ide_version 2.8.1 \
        --override_user_agent_name antigravity \
        --https_server_port 58433 \
        --csrf_token "${CSRF_TOKEN:-antigravity-secure-token}" \
        --app_data_dir antigravity \
        --api_server_url https://generativelanguage.googleapis.com \
        --cloud_code_endpoint https://daily-cloudcode-pa.googleapis.com
else
    exec "$@"
fi
