# Toboggan

🛝 Slide into post-exploitation from RCE with ease. Toboggan wraps your remote command execution into a upgradable dumb shell, making the post-exploitation phase better.

<p align="center">
    <img width="350" src="/media/toboggan-coin-nobg.png" alt="Toboggan Logo">
</p>

Getting started with toboggan is as smooth. You can do this by pulling directly from the repository:
```shell
pip install 'toboggan@git+https://github.com/n3rada/toboggan.git'
``` 

Or, by using [`pipx`](https://pypa.github.io/pipx/) - and you should -, give this a whirl:
```shell
pipx install 'git+https://github.com/n3rada/toboggan.git'
```

Thus, you can execute it with the following command:
```shell
toboggan -m ~/phpexploit.py
```

An RCE (Remote Code Execution) Python3 module is essentially a Python3 source code crafted to manage your remote code execution. For a module to be compatible with Toboggan, it **must** include a method named **execute**. This method **should have two parameters**: `command` of type `str` and `timeout` of type `float`.

## Make Dumb Shell Smarter (`Unix`)
The Unix environment offers a plethora of inter-process communication (IPC) mechanisms. The method used here is known as "named pipe". This one-way IPC is often a go-to when one wishes to emulate a remote interactive shell session over an inherently non-interactive medium - think HTTP requests or rudimentary command execution interfaces.

At its heart, a named pipe, or FIFO (First In, First Out), is an avenue to smoothly transition through an RCE in restrictive scenarios, such as those barricaded behind firewalls, making it feel almost like you're operating in a pseudo-TTY.

## Disclaimer
Toboggan is intended for use in legal penetration testing, Capture The Flag (CTF) competitions, or other authorized and ethical security assessments. Unauthorized use of this tool on systems you do not own or without proper authorization may be illegal. Please use "Toboggan" responsibly and in compliance with applicable laws and regulations.
