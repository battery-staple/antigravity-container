#!/usr/bin/env python3
"""
Antigravity Host-Exec Daemon
Runs on macOS host listening on TCP localhost.
Validates HMAC authentication tokens and whitelist policy before executing commands on host.
"""

import atexit
import hashlib
import hmac
import json
import logging
import os
import re
import select
import shlex
import signal
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

STATE_DIR = os.environ.get("ANTIGRAVITY_STATE_DIR", os.path.expanduser("~/.antigravity-sandbox"))
IPC_DIR = os.path.join(STATE_DIR, "ipc")
LOGS_DIR = os.path.join(STATE_DIR, "logs")
PID_FILE_PATH = os.path.join(IPC_DIR, "host-bridge.pid")
AUTH_SECRET_PATH = os.path.join(IPC_DIR, "auth_secret.key")
WHITELIST_PATH = os.path.join(STATE_DIR, "whitelist.yaml")
HOST_EXEC_BIND = os.environ.get("HOST_EXEC_BIND", "0.0.0.0")
HOST_EXEC_PORT = int(os.environ.get("HOST_EXEC_PORT", "58433"))

# Ensure required state directories exist
os.makedirs(IPC_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    log_handlers.append(logging.FileHandler(os.path.join(LOGS_DIR, "host_exec_daemon.log")))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers,
)

# Global cache for dynamic hot-reloading
_cached_whitelist: Optional[Dict[str, Any]] = None
_last_loaded_mtime: float = 0.0
_last_loaded_path: Optional[str] = None


def get_or_create_secret() -> str:
    """Load or generate the shared HMAC authentication secret."""
    try:
        os.makedirs(IPC_DIR, exist_ok=True)
        os.chmod(IPC_DIR, 0o700)
    except Exception as e:
        logging.warning("Could not set permissions on %s: %s", IPC_DIR, e)

    secret = None
    if os.path.exists(AUTH_SECRET_PATH):
        try:
            with open(AUTH_SECRET_PATH, "r", encoding="utf-8") as f:
                secret = f.read().strip()
        except Exception:
            pass

    if not secret:
        secret = os.urandom(32).hex()

    try:
        with open(AUTH_SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(secret)
        os.chmod(AUTH_SECRET_PATH, 0o600)
    except Exception as e:
        logging.warning("Could not write auth secret to %s: %s", AUTH_SECRET_PATH, e)

    return secret


def _read_yaml_config(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a YAML configuration file safely."""
    try:
        import yaml

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        return yaml.safe_load(content)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", filepath, e)
        return None


def get_command_description(name: str, policy: Dict[str, Any]) -> str:
    """Return explicit description or derive a human-readable fallback."""
    if policy.get("description"):
        return str(policy["description"])
    bin_path = policy.get("binary_path", "")
    bin_name = os.path.basename(bin_path) if bin_path else name
    regex = policy.get("allowed_args_regex", ".*")
    if name != bin_name:
        desc = f"Run '{bin_path}' via alias '{name}'"
    else:
        desc = f"Execute host binary '{bin_path}'"
    if regex not in [".*", "^.*$", ""]:
        clean_regex = regex.lstrip("^").rstrip("$")
        desc += f" (allowed args: {clean_regex})"
    return desc


def load_whitelist() -> Dict[str, Any]:
    """Dynamically load and hot-reload whitelist configuration from disk."""
    global _cached_whitelist, _last_loaded_mtime, _last_loaded_path

    candidate_paths = []
    env_config = os.environ.get("ANTIGRAVITY_WHITELIST_CONFIG")
    if env_config:
        candidate_paths.append(env_config)

    candidate_paths.extend([
        WHITELIST_PATH,
        os.path.join(STATE_DIR, "whitelist.yml"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "whitelist.default.yaml")),
    ])

    active_path = None
    for p in candidate_paths:
        if os.path.exists(p):
            active_path = p
            break

    if active_path:
        try:
            mtime = os.path.getmtime(active_path)
            if _cached_whitelist is not None and _last_loaded_path == active_path and mtime == _last_loaded_mtime:
                return _cached_whitelist
            cfg = _read_yaml_config(active_path)
            if cfg:
                _cached_whitelist = cfg
                _last_loaded_mtime = mtime
                _last_loaded_path = active_path
                logging.info("Loaded whitelist policy from %s (mtime=%s)", active_path, mtime)
                return cfg
        except Exception as e:
            logging.warning("Failed to read/stat whitelist at %s: %s", active_path, e)

    if _cached_whitelist is not None:
        return _cached_whitelist

    # Default policy fallback
    return {
        "allowed_workspaces": [],
        "allowed_commands": {
            "xcodebuild": {
                "binary_path": "/usr/bin/xcodebuild",
                "allowed_args_regex": "^(-version|-showsdks|-list.*)$",
                "require_interactive_approval": False,
                "description": "Apple Xcode build system and SDK inspection",
            },
            "simulator": {
                "binary_path": "/usr/bin/open",
                "allowed_args_regex": "^-a Simulator$",
                "require_interactive_approval": False,
                "description": "Launch Apple iOS Simulator",
            },
            "git-credential-osxkeychain": {
                "binary_path": "/usr/bin/git",
                "allowed_args_regex": "^credential-osxkeychain (get|store|erase)$",
                "require_interactive_approval": True,
                "description": "macOS Keychain Git credential helper",
            },
            "sw_vers": {
                "binary_path": "/usr/bin/sw_vers",
                "allowed_args_regex": "^.*$",
                "require_interactive_approval": False,
                "description": "macOS system version information",
            },
        },
    }


def verify_token(req_dict: Dict[str, Any], token: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature on request payload."""
    canonical_payload = json.dumps(
        {
            "command": req_dict.get("command"),
            "args": req_dict.get("args", []),
            "cwd": req_dict.get("cwd", ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_canonical = hmac.new(
        secret.encode("utf-8"), canonical_payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if hmac.compare_digest(expected_canonical, token):
        return True

    # Support legacy flattened string HMAC for backward compatibility
    legacy_str = f"{req_dict.get('command')} {' '.join(req_dict.get('args', []))}".strip()
    expected_legacy = hmac.new(
        secret.encode("utf-8"), legacy_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_legacy, token)


def prompt_user_approval(command_name: str, args: List[str]) -> bool:
    """Prompt user for confirmation via native macOS AppleScript dialog."""
    try:
        cmd_display = shlex.join([command_name] + args) if isinstance(args, list) else f"{command_name} {args}"
        escaped_cmd = cmd_display.replace("\\", "\\\\").replace('"', '\\"')
        applescript = (
            f'display dialog "Antigravity Container is requesting to execute the following command on your macOS host:\n\n'
            f'{escaped_cmd}\n\nDo you authorize this execution?" '
            f'with title "Antigravity Host Execution Request" '
            f'buttons {{"Deny", "Approve"}} default button "Deny" with icon caution'
        )
        res = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)
        return res.returncode == 0 and "Approve" in res.stdout
    except Exception as e:
        logging.error("Failed to prompt user via osascript: %s", e)
        return False


def resolve_cwd(cwd: Optional[str]) -> str:
    """Resolve working directory on host, falling back to home if invalid."""
    return cwd if cwd and os.path.isdir(cwd) else os.path.expanduser("~")


def handle_client(conn: socket.socket, secret: str):
    """Process an individual client request."""
    try:
        chunks = []
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break

        raw_data = b"".join(chunks).decode("utf-8").strip()
        if not raw_data:
            return
        req = json.loads(raw_data)
        command_name = req.get("command")
        args = req.get("args", [])
        token = req.get("token", "")
        raw_cwd = req.get("cwd")

        whitelist = load_whitelist()

        if not verify_token(req, token, secret):
            logging.warning("HMAC Token verification failed!")
            conn.sendall(
                (json.dumps({"status": "error", "message": "Authentication failed: invalid HMAC token"}) + "\n").encode("utf-8")
            )
            return

        # Handle introspection capability request (__list__)
        if command_name in ["__list__", "__capabilities__"]:
            logging.info("Handled introspection capabilities request (__list__)")
            commands_summary = {}
            for c_name, policy in whitelist.get("allowed_commands", {}).items():
                commands_summary[c_name] = {
                    "binary_path": policy.get("binary_path", ""),
                    "allowed_args_regex": policy.get("allowed_args_regex", ".*"),
                    "require_interactive_approval": policy.get("require_interactive_approval", False),
                    "description": get_command_description(c_name, policy),
                }
            resp = {
                "status": "success",
                "type": "capabilities",
                "allowed_workspaces": whitelist.get("allowed_workspaces", []),
                "allowed_commands": commands_summary,
            }
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return

        full_cmd_str = f"{command_name} {shlex.join(args)}".strip()
        logging.info("Received host execution request: %s", full_cmd_str)

        policies = whitelist.get("allowed_commands", {})
        if command_name not in policies:
            logging.warning("Command '%s' is not in host whitelist!", command_name)
            conn.sendall(
                (json.dumps({
                    "status": "error",
                    "error_type": "not_whitelisted",
                    "message": f"Command '{command_name}' is not whitelisted on host (~/.antigravity-sandbox/whitelist.yaml)",
                }) + "\n").encode("utf-8")
            )
            return

        policy = policies[command_name]
        bin_path = policy["binary_path"]
        args_regex = policy.get("allowed_args_regex", ".*")
        args_str = shlex.join(args) if args else ""
        flat_args_str = " ".join(args)

        if not (re.fullmatch(args_regex, args_str) or re.fullmatch(args_regex, flat_args_str)):
            logging.warning("Arguments '%s' violated policy regex: %s", args_str, args_regex)
            conn.sendall(
                (json.dumps({
                    "status": "error",
                    "error_type": "args_violation",
                    "message": f"Command arguments '{args_str}' violated whitelist pattern ({args_regex}) in ~/.antigravity-sandbox/whitelist.yaml",
                }) + "\n").encode("utf-8")
            )
            return

        # Check if interactive approval is required
        if policy.get("require_interactive_approval", False):
            logging.info("Command '%s' requires interactive approval. Prompting user...", command_name)
            approved = prompt_user_approval(command_name, args)
            if not approved:
                logging.warning("Execution of '%s' was denied by user.", full_cmd_str)
                conn.sendall(
                    (json.dumps({
                        "status": "error",
                        "error_type": "denied_by_user",
                        "message": "Execution denied by user via macOS approval dialog",
                    }) + "\n").encode("utf-8")
                )
                return
            logging.info("Execution approved by user.")

        effective_cwd = resolve_cwd(raw_cwd)
        logging.info("Executing '%s' with cwd='%s'", bin_path, effective_cwd)

        cmd = [bin_path] + args
        proc = subprocess.run(cmd, cwd=effective_cwd, capture_output=True, text=True)
        response = {
            "status": "success",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
    except Exception as e:
        logging.error("Error handling request: %s", e)
        conn.sendall((json.dumps({"status": "error", "message": str(e)}) + "\n").encode("utf-8"))
    finally:
        conn.close()


def cleanup():
    """Clean up PID file on shutdown."""
    if os.path.exists(PID_FILE_PATH):
        try:
            with open(PID_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content and int(content) == os.getpid():
                os.remove(PID_FILE_PATH)
        except Exception:
            pass


atexit.register(cleanup)


def _handle_signal(signum, frame):
    logging.info("Received signal %d, shutting down daemon...", signum)
    cleanup()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    secret = get_or_create_secret()
    initial_whitelist = load_whitelist()

    try:
        with open(PID_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        logging.warning("Could not write PID file to %s: %s", PID_FILE_PATH, e)

    # TCP Socket (For Container Guest over host.docker.internal)
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        tcp_sock.bind((HOST_EXEC_BIND, HOST_EXEC_PORT))
        tcp_sock.listen(10)
        logging.info("Host-Exec Daemon listening on TCP %s:%s", HOST_EXEC_BIND, HOST_EXEC_PORT)
    except Exception as e:
        logging.critical("Failed to bind TCP socket on %s:%s: %s", HOST_EXEC_BIND, HOST_EXEC_PORT, e)
        sys.exit(1)

    num_cmds = len(initial_whitelist.get("allowed_commands", {}))
    logging.info(
        "Host-Exec Daemon is active with %d whitelisted commands. Whitelist will hot-reload on change.", num_cmds
    )

    try:
        while True:
            readable, _, _ = select.select([tcp_sock], [], [])
            for s in readable:
                conn, _ = s.accept()
                handle_client(conn, secret)
    except KeyboardInterrupt:
        logging.info("Shutting down daemon...")
    finally:
        try:
            tcp_sock.close()
        except Exception:
            pass
        cleanup()


if __name__ == "__main__":
    main()
