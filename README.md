# Toboggan

🛝 Slide into post-exploitation from RCE with ease. Toboggan wraps your remote command execution into a upgradable dumb shell, sliding directly into post-exploitation phase. It allows you to fastly launch a `mkfifo` forward-shell inside a targeted Linux environment.

<p align="center">
    <img width="350" src="/media/toboggan-coin-nobg.png" alt="Toboggan Logo">
</p>

## Installation

Installing Toboggan is simple. You can install it directly from the repository:

```shell
pip install 'toboggan@git+https://github.com/n3rada/toboggan.git'
```

### Using [`pipx`](https://pypa.github.io/pipx/)
Be careful, it installs Python applications in isolated virtual environments, which means they do not have access to system-wide packages by default (like `psycopg2`).
```shell
pipx install 'git+https://github.com/n3rada/toboggan.git'
```

If you want-it to use system site packages, pass `--system-site-packages` when installing via `pipx`.

## Execution

Once installed, you can execute it using:
```shell
toboggan -m ~/phpexploit.py
```

When you are knowing what you are doing, you can also do:
```shell
toboggan -m ~/phpexploit.py --camouflage --fifo --os "unix" -wd /dev/shm/apache-tmp
```

It will start a FiFo named-pipe (a.k.a `mkfifo` shell, forward-shell) on `unix` (`--os`) remote system and obfuscating all commands using the [hide.py](./toboggan/actions/hide/unix.py) actions.

### Proxy

You can forward to your favorite proxifier such as your favorite [`Squid`](https://www.squid-cache.org/) server using the `--proxy` parameter:

```shell
toboggan -m ~/phpexploit.py --proxy http://squidrandom.<something>.io:3128
```

### BurpSuite

To route traffic through Burp Suite:
```shell
toboggan -m ~/phpexploit.py --proxy
```

You can also directly import a Burp saved request that contains the `||cmd||` placeholder:
```shell
toboggan -r brequest
```

## 🔍 What is an RCE Python Module?

A Remote Code Execution (RCE) module is a Python script that defines how commands are sent to and executed on a remote system. Toboggan uses this module to wrap and streamline post-exploitation command execution.

To be compatible with Toboggan, your module must define a function with the following exact signature:

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

This function will be called internally by Toboggan to execute commands remotely. It uses [`modwrap`](https://pypi.org/project/modwrap/) under the hood.

### Considerations

Your `execute()` function must handle all quirks of the target system.

- If space characters need to be replaced (e.g., with `${IFS}`), handle that inside the function.
- If special encoding is required (e.g., base64, hex), apply it before sending.
- If the system echoes extra characters or wraps the output, sanitize it.
- If the remote interface is slow or unreliable, tune the timeout.

The goal is for Toboggan to call your `execute()` function with any arbitrary command and get the correct output, as if you typed it in a shell.

## 🏗️ Making Dumb Shells Smarter

### Named Pipes for Semi-Interactive Shells

Toboggan uses named pipes (FIFO - First In, First Out) for inter-process communication (IPC). Named pipes are particularly useful when working with RCE over limited channels like HTTP requests or restricted command execution interfaces. It uses a `mkfifo` command under the hood. Also known as forward-shell style.

This allows Toboggan to simulate pseudo-TTY behavior, even in restricted environments behind firewalls. To enable named pipe mode, use the `--fifo` flag:
```shell
toboggan -m ~/phpexploit.py --fifo
```

Toboggan will create a FIFO-based communication channel, allowing you to interact with the remote system in a more dynamic way (e.g., using `sudo -l`).

## 🛠️ Bring Your Own Actions (BYOA)

Actions in Toboggan are modular plugins that allow you to extend its functionality. Actions can automate common post-exploitation tasks, such as downloading files, executing scripts, or setting up persistent access. Custom actions should be placed in `~/.local/share/toboggan/actions` (Linux) or `%APPDATA%\toboggan\actions` (Windows).

## Disclaimer

Toboggan is intended for use in legal penetration testing, Capture The Flag (CTF) competitions, or other authorized and ethical security assessments. Unauthorized use of this tool on systems you do not own or without proper authorization may be illegal. Please use "Toboggan" responsibly and in compliance with applicable laws and regulations.
