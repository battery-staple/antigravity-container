# Antigravity Container Execution Environment

You are operating inside a secure, isolated Linux container (Ubuntu 24.04) running in Docker/OrbStack on behalf of the developer.

## 1. Two-Tier Sandbox Architecture & Mental Model
There are two distinct, independent security layers:

1. **Outer Layer — Docker Container (This Project)**:
   - Your entire execution environment is contained inside an isolated Linux container.
   - Host macOS system files, `~/.ssh`, `~/.aws`, Keychain, and files outside whitelisted workspaces are physically isolated and inaccessible directly.
   - Whitelisted workspaces are mounted directly to their host absolute paths (e.g. `/Users/...`), maintaining full path parity across host and container.
   - Your home directory `/home/developer` resides on a persistent volume preserving dotfiles, package caches, and agent state across container restarts.

2. **Inner Layer — Antigravity Tool Security Policy (`BypassSandbox`)**:
   - Inside this container, the `run_command` tool still operates Antigravity's built-in command security policy.
   - `BypassSandbox: false` (default) disables container network access and restricts writes to workspace directories to allow safe commands to auto-run without prompting the user.
   - `BypassSandbox: true` enables network access and container root filesystem permissions for that command, prompting the user for approval.

## 2. Using `BypassSandbox` Inside the Container
- **`BypassSandbox: true` NEVER breaks out of the Docker container.** It cannot compromise the developer's macOS host.
- **When to use `BypassSandbox: false` (Default)**: Use for offline, workspace-local operations (running local tests, reading/editing code, compiling with pre-installed compilers, git commands, offline builds).
- **When to use `BypassSandbox: true`**: Use whenever a command needs internet/network access (e.g., `sudo apt-get install`, `npm install`, `pip install`, `cargo build` pulling crates, `curl`, `wget`) or needs to modify container system paths outside the workspace (e.g., `/etc`, `/usr`, `/var`).

## 3. macOS Host Binary Execution (`host-exec`)
- Because you are operating inside an isolated Linux container, macOS-native host binaries cannot be executed directly via Linux shell commands.
- Whenever you need to invoke macOS host tools or system utilities, use the `host-exec` bridge tool (`host-exec <command> [args...]`).
- **Discovering Permitted Host Commands**: To inspect the currently active whitelist of host tools, permitted argument patterns, and approval policies, consult the `host-exec` skill or run `host-exec --list`.
- **Host Bridge Offline Remediation**: If `host-exec` returns `[HOST-EXEC ERROR] Host Bridge Daemon is not running on the macOS host`, do not retry in a loop. Ask the user to start the host bridge by running `antigravity-sandbox host-bridge` (or `./scripts/antigravity-sandbox host-bridge`) on their macOS host. Once the user confirms it is running, retry the command.
