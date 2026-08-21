#!/usr/bin/env python3
"""
Antigravity Host-Exec Daemon
Runs on macOS host listening on local Unix Domain Socket and TCP localhost.
Validates HMAC authentication tokens and whitelist policy before executing commands on host.
"""

import os
import sys
import json
import re
import hmac
import hashlib
import socket
import subprocess
import logging
import shlex
import select

STATE_DIR = os.environ.get("ANTIGRAVITY_STATE_DIR", os.path.expanduser("~/.antigravity-sandbox"))
IPC_DIR = os.path.join(STATE_DIR, "ipc")
LOGS_DIR = os.path.join(STATE_DIR, "logs")
SOCKET_PATH = os.path.join(IPC_DIR, "host-exec.sock")
AUTH_SECRET_PATH = os.path.join(IPC_DIR, "auth_secret.key")
WHITELIST_PATH = os.path.join(STATE_DIR, "whitelist.json")

# Ensure required directories exist
os.makedirs(IPC_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    log_handlers.append(logging.FileHandler(os.path.join(LOGS_DIR, "host_exec_daemon.log")))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers
)

def get_or_create_secret():
    try:
        os.makedirs(IPC_DIR, exist_ok=True)
        os.chmod(IPC_DIR, 0o700)
    except Exception as e:
        logging.warning(f"Could not set permissions on {IPC_DIR}: {e}")

    secret = None
    if os.path.exists(AUTH_SECRET_PATH):
        try:
            with open(AUTH_SECRET_PATH, "r") as f:
                secret = f.read().strip()
        except Exception:
            pass

    if not secret:
        secret = os.urandom(32).hex()

    try:
        with open(AUTH_SECRET_PATH, "w") as f:
            f.write(secret)
        os.chmod(AUTH_SECRET_PATH, 0o600)
    except Exception as e:
        logging.warning(f"Could not write auth secret to {AUTH_SECRET_PATH}: {e}")

    return secret

def load_whitelist():
    # 1. Custom env var override
    env_config = os.environ.get("ANTIGRAVITY_WHITELIST_CONFIG")
    if env_config and os.path.exists(env_config):
        try:
            with open(env_config, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to parse ANTIGRAVITY_WHITELIST_CONFIG ({env_config}): {e}")

    # 2. Global user config (~/.antigravity-sandbox/whitelist.json)
    if os.path.exists(WHITELIST_PATH):
        try:
            with open(WHITELIST_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to parse {WHITELIST_PATH}: {e}")

    # 3. Default template from repository
    repo_default = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "whitelist.default.json"))
    if os.path.exists(repo_default):
        try:
            with open(repo_default, "r") as f:
                return json.load(f)
        except Exception:
            pass

    # 4. Default policy fallback
    return {
        "allowed_workspaces": [],
        "allowed_commands": {
            "xcodebuild": {
                "binary_path": "/usr/bin/xcodebuild",
                "allowed_args_regex": "^(-version|-showsdks|-list.*)$",
                "require_interactive_approval": False
            },
            "simulator": {
                "binary_path": "/usr/bin/open",
                "allowed_args_regex": "^-a Simulator$",
                "require_interactive_approval": False
            },
            "git-credential-osxkeychain": {
                "binary_path": "/usr/bin/git",
                "allowed_args_regex": "^credential-osxkeychain (get|store|erase)$",
                "require_interactive_approval": True
            },
            "sw_vers": {
                "binary_path": "/usr/bin/sw_vers",
                "allowed_args_regex": "^.*$",
                "require_interactive_approval": False
            }
        }
    }

def verify_token(req_dict, token, secret):
    # Primary: Canonical structured JSON HMAC verification
    canonical_payload = json.dumps({
        "command": req_dict.get("command"),
        "args": req_dict.get("args", []),
        "cwd": req_dict.get("cwd", "")
    }, sort_keys=True, separators=(',', ':'))
    expected_canonical = hmac.new(secret.encode("utf-8"), canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected_canonical, token):
        return True

    # Fallback: Support legacy flattened string HMAC for backward compatibility
    legacy_str = f"{req_dict.get('command')} {' '.join(req_dict.get('args', []))}".strip()
    expected_legacy = hmac.new(secret.encode("utf-8"), legacy_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_legacy, token)

def prompt_user_approval(command_name, args):
    try:
        if isinstance(args, list):
            cmd_display = shlex.join([command_name] + args)
        else:
            cmd_display = f"{command_name} {args}"
        # Escape backslashes first, then double quotes to prevent AppleScript syntax malformation
        escaped_cmd = cmd_display.replace('\\', '\\\\').replace('"', '\\"')
        applescript = (
            f'display dialog "Antigravity Container is requesting to execute the following command on your macOS host:\n\n'
            f'{escaped_cmd}\n\nDo you authorize this execution?" '
            f'with title "Antigravity Host Execution Request" '
            f'buttons {{"Deny", "Approve"}} default button "Deny" with icon caution'
        )
        res = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)
        if res.returncode == 0 and "Approve" in res.stdout:
            return True
        return False
    except Exception as e:
        logging.error(f"Failed to prompt user via osascript: {e}")
        return False

def translate_cwd(container_cwd, whitelist=None):
    # 1. Direct host path match (Host-Path Mirroring)
    if os.path.isdir(container_cwd):
        return container_cwd

    # 2. Check whitelisted workspaces if path begins with legacy /workspace
    repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if whitelist and whitelist.get("allowed_workspaces"):
        allowed = whitelist["allowed_workspaces"]
        if container_cwd.startswith("/workspace") and len(allowed) > 0:
            rel = os.path.relpath(container_cwd, "/workspace")
            candidate = os.path.join(allowed[0], rel) if rel != "." else allowed[0]
            if os.path.isdir(candidate):
                return candidate

    host_workspace = os.environ.get("HOST_WORKSPACE_PATH")
    if host_workspace and os.path.isdir(host_workspace):
        return host_workspace

    return repo_dir if os.path.isdir(repo_dir) else os.path.expanduser("~")

def handle_client(conn, secret, whitelist):
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
        raw_cwd = req.get("cwd", "/workspace")

        full_cmd_str = f"{command_name} {shlex.join(args)}".strip()
        logging.info(f"Received host execution request: {full_cmd_str}")

        if not verify_token(req, token, secret):
            logging.warning("HMAC Token verification failed!")
            conn.sendall((json.dumps({"status": "error", "message": "Authentication failed: invalid HMAC token"}) + "\n").encode("utf-8"))
            return

        policies = whitelist.get("allowed_commands", {})
        if command_name not in policies:
            logging.warning(f"Command '{command_name}' is not in host whitelist!")
            conn.sendall((json.dumps({"status": "error", "message": f"Command '{command_name}' is not whitelisted on host (~/.antigravity-sandbox/whitelist.json)"}) + "\n").encode("utf-8"))
            return

        policy = policies[command_name]
        bin_path = policy["binary_path"]
        args_regex = policy.get("allowed_args_regex", ".*")
        args_str = shlex.join(args) if args else ""
        flat_args_str = " ".join(args)

        if not (re.fullmatch(args_regex, args_str) or re.fullmatch(args_regex, flat_args_str)):
            logging.warning(f"Arguments '{args_str}' violated policy regex: {args_regex}")
            conn.sendall((json.dumps({"status": "error", "message": f"Command arguments '{args_str}' violated whitelist pattern ({args_regex}) in ~/.antigravity-sandbox/whitelist.json"}) + "\n").encode("utf-8"))
            return

        # Check if interactive approval is required
        if policy.get("require_interactive_approval", False):
            logging.info(f"Command '{command_name}' requires interactive approval. Prompting user...")
            approved = prompt_user_approval(command_name, args)
            if not approved:
                logging.warning(f"Execution of '{full_cmd_str}' was denied by user.")
                conn.sendall((json.dumps({"status": "error", "message": "Execution denied by user via macOS approval dialog"}) + "\n").encode("utf-8"))
                return
            logging.info("Execution approved by user.")

        # Translate cwd from container path to host path safely
        effective_cwd = translate_cwd(raw_cwd, whitelist)
        logging.info(f"Executing '{bin_path}' with cwd='{effective_cwd}'")

        # Execute safe command on host
        cmd = [bin_path] + args
        proc = subprocess.run(cmd, cwd=effective_cwd, capture_output=True, text=True)
        response = {
            "status": "success",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
    except Exception as e:
        logging.error(f"Error handling request: {e}")
        conn.sendall((json.dumps({"status": "error", "message": str(e)}) + "\n").encode("utf-8"))
    finally:
        conn.close()

HOST_EXEC_BIND = os.environ.get("HOST_EXEC_BIND", "0.0.0.0")
HOST_EXEC_PORT = int(os.environ.get("HOST_EXEC_PORT", "58433"))

def main():
    secret = get_or_create_secret()
    whitelist = load_whitelist()

    sockets_to_watch = []

    # 1. Setup TCP Socket (For Container Guest over host.docker.internal)
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        tcp_sock.bind((HOST_EXEC_BIND, HOST_EXEC_PORT))
        tcp_sock.listen(10)
        sockets_to_watch.append(tcp_sock)
        logging.info(f"Host-Exec Daemon listening on TCP {HOST_EXEC_BIND}:{HOST_EXEC_PORT}")
    except Exception as e:
        logging.error(f"Failed to bind TCP socket on {HOST_EXEC_BIND}:{HOST_EXEC_PORT}: {e}")

    # 2. Setup Unix Domain Socket (For local macOS host IPC)
    os.makedirs(IPC_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except Exception:
            pass

    unix_sock = None
    try:
        unix_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_sock.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)
        unix_sock.listen(10)
        sockets_to_watch.append(unix_sock)
        logging.info(f"Host-Exec Daemon listening on Unix socket {SOCKET_PATH}")
    except Exception as e:
        logging.warning(f"Failed to bind Unix domain socket on {SOCKET_PATH}: {e}")

    if not sockets_to_watch:
        logging.critical("No sockets available to listen on. Exiting.")
        sys.exit(1)

    logging.info(f"Host-Exec Daemon is active. Whitelist loaded from {WHITELIST_PATH}")
    try:
        while True:
            readable, _, _ = select.select(sockets_to_watch, [], [])
            for s in readable:
                conn, _ = s.accept()
                handle_client(conn, secret, whitelist)
    except KeyboardInterrupt:
        logging.info("Shutting down daemon...")
    finally:
        for s in sockets_to_watch:
            try:
                s.close()
            except Exception:
                pass
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except Exception:
                pass

if __name__ == "__main__":
    main()
