---
name: host-exec
description: Use this skill to execute whitelisted macOS host binaries (e.g. xcodebuild, iOS Simulator, macOS Keychain, macOS notarization) from inside the Linux container sandbox using the host-exec bridge tool.
---

# Host-Exec Skill (Host Binary Execution Bridge)

Use this skill when you need to invoke tools or commands that only exist on the developer's macOS host machine (outside the Linux container).

## 1. When to Use `host-exec`

| Task / Tool Required | Direct Shell vs `host-exec` | Example Command |
| :--- | :--- | :--- |
| **Standard Linux / Dev Tools** (Node, Python, Go, Rust, Git, gcc, make, bash) | **Run directly in container** | `npm test`, `cargo build`, `python main.py` |
| **Xcode & Apple SDKs** (`xcodebuild`, `xcrun`, `swiftc` for iOS/macOS) | **Use `host-exec`** | `host-exec xcodebuild -showsdks` |
| **iOS Simulator** (Launch simulator app on macOS) | **Use `host-exec`** | `host-exec open -a Simulator` |
| **macOS Keychain** (`git-credential-osxkeychain`, `security`) | **Use `host-exec`** | `host-exec git credential-osxkeychain get` |

---

## 2. Command Syntax & Usage

Run the `host-exec` CLI tool followed by the host command and its arguments:

```bash
host-exec <command> [args...]
```

### Examples:
```bash
# Check Xcode version on macOS
host-exec xcodebuild -version

# List available Xcode SDKs
host-exec xcodebuild -showsdks

# Launch macOS iOS Simulator
host-exec open -a Simulator

# Retrieve credentials from macOS Keychain
echo "host=github.com\nprotocol=https" | host-exec git credential-osxkeychain get
```

---

## 3. How the Bridge Works Under the Hood

1. **Path Translation**:
   - When you execute `host-exec` from a whitelisted directory, the host bridge automatically matches the container path with the host filesystem path.
2. **HMAC-SHA256 Authentication**:
   - `host-exec` signs every request with a secret token shared between the host daemon and the container.
3. **Interactive User Approval**:
   - If a command is configured with `"require_interactive_approval": true` in `~/.antigravity-sandbox/whitelist.json`, a native macOS dialog will appear on the developer's screen with **Approve** / **Deny** buttons.
   - *Note*: If the command is waiting for user approval, do not spam repeated executions.

---

## 4. Handling Whitelist Rejections

If a command fails with an error such as:
`Host execution rejected: Command 'foo' is not in whitelist policy`

**Guidance for Agent**:
1. Inform the user that the command `foo` is not currently whitelisted in the host security policy.
2. Direct the user to edit their `~/.antigravity-sandbox/whitelist.json` file on macOS to whitelist the binary and allowed argument patterns if they wish to permit it.
