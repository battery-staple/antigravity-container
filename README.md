# Antigravity Sandbox: Docker Runtime for Google Antigravity Desktop App

A production-grade, high-performance sandboxing solution designed specifically for the **Google Antigravity Desktop App** (`/Applications/Antigravity.app` on macOS) using **Docker / OrbStack**.

---

## Key Capabilities

- **100% Boundary Isolation**: The AI Agent executes terminal commands (`bash`, `zsh`, `npm`, `pip`, `rm -rf`) inside an isolated Linux container. Host macOS system files, `~/.ssh`, `~/.aws`, Keychain, and home directories outside the workspace are physically inaccessible.
- **Local Direct File Editing**: Edit your code on macOS in your preferred native editor (VS Code, Cursor, JetBrains, Zed, Antigravity IDE). File updates synchronize into the sandbox in **<1ms** via macOS **VirtioFS**.
- **Shared History with Antigravity IDE**: Conversation history, brain logs, and artifacts (`~/.gemini/antigravity/brain`) synchronize in real-time between the host IDE and the sandbox container.
- **Native GUI Fluidity & Browser Support**: Connect directly in any desktop web browser (`https://localhost:58432`) or launch the native macOS Electron app with 120Hz ProMotion GPU acceleration.
- **User Persistence**: User dotfiles, tool caches, Python virtual environments, and agent memory persist across restarts via named Docker volumes. Base compilers and packages are managed cleanly in `Dockerfile.sandbox`.
- **Host-Exec Bridge**: Securely invoke whitelisted host macOS binaries (e.g. `xcodebuild`, iOS Simulator) from within the sandbox via HMAC-authenticated TCP bridge with native macOS dialog approvals.
- **Granular Multi-Project Mounting**: Whitelist and mount individual project directories without exposing parent directories.

---

## Quickstart

### 1. Prerequisites
- macOS (Apple Silicon M1/M2/M3/M4 or Intel)
- Docker Desktop (with VirtioFS enabled) OR OrbStack

### 2. Whitelist Workspaces and Start the Sandbox
```bash
# Link CLI tool to PATH (optional)
ln -sf $(pwd)/scripts/antigravity-sandbox /usr/local/bin/antigravity-sandbox

# Whitelist your project workspace (defaults to current directory if omitted)
antigravity-sandbox workspace add $(pwd)

# Start the sandbox (automatically builds image and launches Language Server)
antigravity-sandbox start
```

### 3. Connect to the Frontend / IDE
- **Web Browser**: Open [`https://localhost:58432`](https://localhost:58432) *(Bypass the local self-signed certificate prompt: click **Advanced** $\rightarrow$ **Proceed to localhost**)*.
- **Native macOS App**: Run `antigravity-sandbox app` to launch `/Applications/Antigravity.app` connected directly to the sandboxed daemon.
- **Antigravity IDE**: Press <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> $\rightarrow$ **`Dev Containers: Attach to Running Container...`** $\rightarrow$ select **`antigravity-sandbox`**.

---

## Built-In Language Server & Web UI (`https://localhost:58432`)

The container image automatically downloads and bundles the Linux `language_server` binary directly into `/usr/local/bin/language_server` at build time. When you start the container, the Antigravity Language Server daemon and Web UI are active immediately:

- **Web UI**: Navigate to `https://localhost:58432` in any browser.
- **Native App**: Launch `/Applications/Antigravity.app` connected to the sandbox via:
  ```bash
  antigravity-sandbox app
  ```

---

## Antigravity IDE Integration

1. **Shared Authentication & History**: The host directory `~/.gemini` (OAuth tokens, Google account session, brain logs, and artifacts) is mounted into the container. When you start the sandbox, it automatically inherits your host Google login state without requiring a separate web browser login.
2. **In-IDE Sandboxing**: If you want all agent commands triggered from inside the Antigravity IDE to run sandboxed:
   - In Antigravity IDE, press <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>.
   - Run **`Dev Containers: Attach to Running Container...`** $\rightarrow$ select **`antigravity-sandbox`**.

---

## Toolchain & Package Management

### Declarative Toolchains (`Dockerfile.sandbox`)
System libraries and base compilers are defined in [`Dockerfile.sandbox`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/Dockerfile.sandbox). To add packages (e.g. `cmake`, `llvm`, `ffmpeg`), edit `Dockerfile.sandbox` and run:
```bash
./scripts/antigravity-sandbox build
```

### User Persistence (`antigravity_home_persist`)
The `/home/developer` volume retains state across restarts:
- `npm install -g <pkg>`: Installs to `~/.npm-global` without root and persists across container recreations.
- `pip install --user <pkg>`: Installs to `~/.local` and persists across container recreations.

---

## Workspace Whitelisting & Multi-Project Management

Workspaces are persisted globally in `~/.antigravity-sandbox/whitelist.json` and mounted directly to their **exact host absolute paths** inside the container with sub-millisecond VirtioFS sync.

```bash
# Add a workspace to whitelist (defaults to current working directory)
antigravity-sandbox workspace add /path/to/project-alpha

# Add another workspace (automatically updates running container mounts)
antigravity-sandbox workspace add /path/to/project-beta

# List all whitelisted workspaces
antigravity-sandbox workspace list

# Remove a workspace
antigravity-sandbox workspace remove /path/to/project-alpha
```

---

## Host-Exec Bridge (Host Binary Execution)

To allow the sandboxed agent to run specific host macOS binaries (e.g. `xcodebuild`, iOS Simulator, or Keychain):

1. Start the bridge daemon on your macOS host:
   ```bash
   ./scripts/antigravity-sandbox host-bridge
   ```
2. Configure permissions in `~/.antigravity-sandbox/whitelist.json`.
3. Commands with `"require_interactive_approval": true` will trigger a native macOS confirmation dialog before running.

---

## Documentation Links

- **Architecture Blueprint**: [`design/antigravity_sandbox_architecture.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/antigravity_sandbox_architecture.md)
- **Future Improvement (Snapshots & Instant Rollbacks)**: [`design/future/snapshots_future_improvement.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/future/snapshots_future_improvement.md)
- **Future Improvement (Egress Sidecar Filtering)**: [`design/future/egress_filtering_future_improvement.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/future/egress_filtering_future_improvement.md)
