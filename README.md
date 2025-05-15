# Toboggan

🛝 Slide into post-exploitation from RCE with ease. Toboggan wraps your remote command execution into a upgradable dumb shell, making the post-exploitation phase better.

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
toboggan -m ~/phpexploit.py --hide --fifo --os "unix" -wd /dev/shm/apache-tmp
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

A Remote Code Execution (RCE) module is a Python script designed to handle remote command execution. To be compatible with Toboggan, the module must include an execute function with the following signature:

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

## 🏗️ Making Dumb Shells Smarter

### Named Pipes for Semi-Interactive Shells
Toboggan uses named pipes (FIFO - First In, First Out) for inter-process communication (IPC). Named pipes are particularly useful when working with RCE over limited channels like HTTP requests or restricted command execution interfaces.

This allows Toboggan to simulate pseudo-TTY behavior, even in restricted environments behind firewalls. To enable named pipe mode, use the `--fifo` flag:
```shell
toboggan -m ~/phpexploit.py --fifo
```

Toboggan will create a FIFO-based communication channel, allowing you to interact with the remote system in a more dynamic way (e.g., using `sudo -l`).

## 🛠️ Actions: Customizable Remote Interactions

Actions in Toboggan are modular plugins that allow you to extend its functionality. Actions can automate common post-exploitation tasks, such as downloading files, executing scripts, or setting up persistent access.

### Custom Actions
Custom actions allow you to define your own automation workflows. Actions should be placed in `~/.local/share/toboggan/actions` (Linux) or `%APPDATA%\toboggan\actions` (Windows).

## Disclaimer
Toboggan is intended for use in legal penetration testing, Capture The Flag (CTF) competitions, or other authorized and ethical security assessments. Unauthorized use of this tool on systems you do not own or without proper authorization may be illegal. Please use "Toboggan" responsibly and in compliance with applicable laws and regulations.
