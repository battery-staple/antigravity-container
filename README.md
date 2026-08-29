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

# Start the sandbox (automatically builds image, launches Language Server, and spawns host-bridge)
antigravity-sandbox start

# Or start without the background host-bridge daemon:
# antigravity-sandbox start --no-host-bridge
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
System libraries and base compilers are defined in [`Dockerfile.sandbox`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/Dockerfile.sandbox). Pre-installed development toolchains include:
- **Java**: OpenJDK 21 (LTS) (`javac`, `java`, `JAVA_HOME=/usr/lib/jvm/java-21`)
- **Kotlin**: Kotlin CLI Compiler v2.1.10 (`kotlinc`, `kotlin`, `kotlinc-jvm`)
- **Build Tools**: Gradle v8.12.1 (`gradle`, `GRADLE_USER_HOME=/home/developer/.gradle`)
- **Linters & Formatters**: `ktlint` (Kotlin code style / linter) and `google-java-format` (Google Java style formatter)
- **Node.js & JavaScript**: Node.js v22 (LTS), `npm`, `yarn`, `pnpm`, `bun`
- **Go**: Go v1.23 (`go`, `GOPATH=/home/developer/go`)
- **Python**: Python 3.12 (`python3`, `pip`, `venv`)
- **C/C++**: `build-essential` (`gcc`, `g++`, `make`)

To add further packages (e.g. `cmake`, `llvm`, `ffmpeg`), edit `Dockerfile.sandbox` and run:
```bash
./scripts/antigravity-sandbox build
```

### User Persistence (`antigravity_home_persist`)
The `/home/developer` volume retains state across restarts:
- `npm install -g <pkg>`: Installs to `~/.npm-global` without root and persists across container recreations.
- `pip install --user <pkg>`: Installs to `~/.local` and persists across container recreations.
- `~/.gradle`: Gradle dependency and build artifact caches persist automatically.
- `~/go`: Go module cache and user binaries persist across container recreations.

---

## Workspace Whitelisting & Multi-Project Management

Workspaces are persisted globally in `~/.antigravity-sandbox/whitelist.yaml` and mounted directly to their **exact host absolute paths** inside the container with sub-millisecond VirtioFS sync.

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

## Sandbox-Specific Global Rules (`~/.antigravity-sandbox/rules/*.md`)

Define global agent rules that only apply when running inside the sandbox container.

Place any Markdown files into `~/.antigravity-sandbox/rules/`. The sandbox compiles these alongside built-in container rules and host global rules into `~/.antigravity-sandbox/GEMINI.md`, which is mounted into the container while keeping your host macOS `~/.gemini/GEMINI.md` untouched.

```bash
# Inspect active rules and compilation status
antigravity-sandbox rules
```

---

## Sandbox Directory & Quick Open (`~/.antigravity-sandbox`)

Quickly open the sandbox directory in Finder (macOS) or system file manager to edit rules, inspect `whitelist.yaml`, or check logs:

```bash
# Open ~/.antigravity-sandbox in Finder / file manager
antigravity-sandbox open

# Open a specific subdirectory or file
antigravity-sandbox open rules
antigravity-sandbox open whitelist.yaml
```

---

## Host-Exec Bridge (macOS Host Tools)

Because the container runs Linux, macOS-only tools (e.g., Xcode / `xcodebuild`, iOS Simulator, macOS Keychain) cannot execute directly in the sandbox. The Host-Exec bridge allows the agent to invoke specific macOS binaries on the host system under strict security guardrails.

### Starting and Managing the Daemon
`antigravity-sandbox start` spawns the host-bridge daemon in the background automatically (unless `--no-host-bridge` is passed).

You can also manage or inspect the daemon directly on your macOS host:
```bash
# Check daemon status
antigravity-sandbox host-bridge status

# Start daemon in background
antigravity-sandbox host-bridge start

# Stop daemon
antigravity-sandbox host-bridge stop

# Restart daemon
antigravity-sandbox host-bridge restart

# Run daemon in foreground (for interactive debugging)
antigravity-sandbox host-bridge fg
```

### Configuration & Security
- **Whitelist Policy (`~/.antigravity-sandbox/whitelist.yaml`)**: The single source of truth for allowed binaries and argument regex patterns. Changes reload automatically without restarting the daemon.
- **Interactive Approvals**: Set `require_interactive_approval: true` on sensitive commands to prompt you with a native macOS confirmation dialog before the command runs.
- **HMAC Authentication**: All execution requests are signed and verified with a local shared secret.

*Inside the container, the agent automatically invokes permitted tools via `host-exec <command>` (and can inspect active policies with `host-exec --list`).*

---

## Documentation Links

- **Architecture Blueprint**: [`design/antigravity_sandbox_architecture.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/antigravity_sandbox_architecture.md)
- **Future Improvement (Snapshots & Instant Rollbacks)**: [`design/future/snapshots_future_improvement.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/future/snapshots_future_improvement.md)
- **Future Improvement (Egress Sidecar Filtering)**: [`design/future/egress_filtering_future_improvement.md`](file:///Users/rohengiralt/Documents/Code/LLM/antigravity-container/design/future/egress_filtering_future_improvement.md)
