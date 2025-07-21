#!/usr/bin/env python3

# Built-in imports
import argparse
import os
from pathlib import Path

# External library imports
from modwrap import ModuleWrapper
import httpx

# Local library imports
from toboggan.core import logbook
from toboggan.core import executor
from toboggan.core import terminal

from toboggan.core import utils


# Directory where built-in handlers are stored
BUILTIN_DIR = Path(__file__).parent / "core/handlers"


def run() -> int:
    parser = argparse.ArgumentParser(
        prog="toboggan",
        add_help=True,
        description="Bring intelligence to any remote command execution (RCE).",
    )

    # Argument Groups
    execution_group = parser.add_argument_group(
        "Execution Configuration", "Options to configure how commands are executed."
    )
    named_pipe_group = parser.add_argument_group(
        "Named Pipe Settings", "Options to manage named pipe."
    )
    system_group = parser.add_argument_group(
        "System Configuration", "Specify the target operating system."
    )
    advanced_group = parser.add_argument_group(
        "Advanced Options", "Additional advanced or debugging options."
    )

    execution_group.add_argument(
        "--exec-wrapper",
        type=str,
        default=None,
        help="OS shell command with placeholder ||cmd||.",
    )
    execution_group.add_argument(
        "-m",
        "--module",
        type=str,
        default=None,
        help="Module path to be imported and executed.",
    )
    execution_group.add_argument(
        "-r",
        "--request",
        type=str,
        default=None,
        help="Burp request with placeholder ||cmd||.",
    )
    execution_group.add_argument(
        "-b64",
        "--base64",
        action="store_true",
        required=False,
        help="Base64-encode every command before execution.",
    )
    execution_group.add_argument(
        "--hide",
        action="store_true",
        required=False,
        help="Obfuscate the command to execute using hide and unhide actions.",
    )

    # Named Pipe Settings
    named_pipe_group.add_argument(
        "--fifo",
        action="store_true",
        required=False,
        help="Start a semi-interactive session using a FIFO (named pipe).",
    )

    named_pipe_group.add_argument(
        "-ri",
        "--read-interval",
        type=float,
        default=0.4,
        help="Interval (in seconds) for reading output from the named pipe.",
    )

    named_pipe_group.add_argument(
        "-i",
        "--stdin",
        type=str,
        default=None,
        help="Input file name (FIFO) where commands go.",
    )

    named_pipe_group.add_argument(
        "-o",
        "--stdout",
        type=str,
        default=None,
        help="Output file name where command output appears.",
    )

    named_pipe_group.add_argument(
        "--shell",
        type=str,
        default=None,
        help=(
            "Specify the shell binary to be used for named pipe execution (e.g., /bin/sh, /bin/bash)"
        ),
    )

    system_group.add_argument(
        "--os",
        type=str,
        choices=["unix", "windows"],
        required=False,
        help="Specify the target operating system (unix or windows).",
    )
    system_group.add_argument(
        "-wd",
        "--working-directory",
        type=str,
        default=None,
        required=False,
        help="Specify the target working directory.",
    )

    parser.add_argument(
        "--proxy",
        type=str,
        nargs="?",
        const="http://127.0.0.1:8080",
        help="Set HTTP(S) proxy, e.g. 'http://127.0.0.1:8080'. Default is Burp Suite proxy.",
    )

    advanced_group.add_argument(
        "--debug",
        action="store_true",
        required=False,
        help="Enable debug logging mode.",
    )

    # Parse arguments
    args = parser.parse_args()

    print(utils.banner())

    env = os.environ

    # Set log level to DEBUG if --debug is passed
    if args.debug:
        env["LOG_LEVEL"] = "DEBUG"

    logger = logbook.get_logger()

    if args.proxy:
        os.environ["http_proxy"] = args.proxy
        os.environ["https_proxy"] = args.proxy
        logger.info(f"🌐 Proxy set to {args.proxy}")

    public_ip = None
    try:
        with httpx.Client(verify=False, http1=True, http2=False) as client:
            response = client.get("https://api.ipify.org?format=json", timeout=15)
            if response.status_code == 200:
                public_ip = response.json().get("ip", None)
    except httpx.TimeoutException:
        logger.error("Request timed-out.")
    except Exception as e:
        logger.warning(f"⚠️ Error retrieving public IP: {e}")

    if public_ip is None:
        return 1

    logger.info(f"🌍 Public IP: {public_ip}")

    execution_module = None

    if args.exec_wrapper:
        logger.info(f"Using OS command wrapper: '{args.exec_wrapper}'.")
        wrapper = ModuleWrapper(BUILTIN_DIR / "os_command.py")
        execution_module = wrapper.module
        execution_module.BASE_CMD = args.exec_wrapper
        logger.info("Use OS system command as base.")
    elif args.request:
        wrapper = ModuleWrapper(BUILTIN_DIR / "burpsuite.py")
        execution_module = wrapper.module
        execution_module.BURP_REQUEST_OBJECT = execution_module.BurpRequest(
            args.request
        )
        logger.info("Use Burpsuite request as base.")
    elif args.module:
        logger.info(f"Use provided module: '{args.module}'.")

        wrapper = ModuleWrapper(args.module)

        wrapper.validate_signature(
            func_name="execute", expected_args=[("command", str), ("timeout", float)]
        )

        execution_module = wrapper.module
    else:
        logger.error("No module provided. I cannot slide on anything.")
        return 1

    if args.base64:
        logger.info("🔐 Base64 encoding enabled for all commands.")

    try:
        command_executor = executor.Executor(
            execute_method=execution_module.execute,
            working_directory=args.working_directory,
            target_os=args.os,
            base64_wrapping=args.base64,
            hide=args.hide,
        )

        remote_terminal = terminal.Terminal(executor=command_executor)

        if command_executor.target.os == "unix":
            if args.fifo:
                logger.info(
                    "🤏 Making your dumb shell semi-interactive using 'fifo' action."
                )
                command_executor.os_helper.start_named_pipe(
                    action_class=command_executor.action_manager.get_action("fifo"),
                    read_interval=args.read_interval,
                    command_in=args.stdin,
                    command_out=args.stdout,
                    shell=args.shell,
                )

        remote_terminal.start()
    except Exception:
        logger.exception("Unhandled exception occurred")

    logger.success("Toboggan execution completed.")
