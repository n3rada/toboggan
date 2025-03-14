#!/usr/bin/env python3

# Built-in imports
import argparse
import traceback
import os
import types
import inspect
from pathlib import Path

# Local library imports
from toboggan.core import logbook
from toboggan.core import loader
from toboggan.core import executor
from toboggan.core import terminal

from toboggan.core.utils import banner


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
        "--shell",
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
        "-rid",
        "--read-interval",
        type=float,
        default=0.4,
        help="Interval (in seconds) for reading output from the named pipe. Default is 0.4s.",
    )

    named_pipe_group.add_argument(
        "-i",
        "--stdin",
        type=str,
        default="tampi",
        help="Input file name, where commands goes.",
    )

    named_pipe_group.add_argument(
        "-o",
        "--stdout",
        type=str,
        default="tampo",
        help="Output file name, where commands output goes.",
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

    advanced_group.add_argument(
        "-b",
        "--burp",
        action="store_true",
        required=False,
        help="Pass the traffic through Burp Suite default proxy (i.e., 127.0.0.1:8080).",
    )
    advanced_group.add_argument(
        "--debug",
        action="store_true",
        required=False,
        help="Enable debug logging mode.",
    )

    # Parse arguments
    args = parser.parse_args()

    print(banner())

    env = os.environ

    # Set log level to DEBUG if --debug is passed
    if args.debug:
        env["LOG_LEVEL"] = "DEBUG"

    logger = logbook.get_logger()

    if args.burp:
        env["http_proxy"] = "http://127.0.0.1:8080"
        env["https_proxy"] = "http://127.0.0.1:8080"

        logger.info("HTTP proxies set to '127.0.0.1:8080'")

    execution_module = None

    if args.shell:
        execution_module = loader.load_module("os_command")
        execution_module.BASE_CMD = args.shell
        logger.info("Use OS system command as base.")
    elif args.request:
        execution_module = loader.load_module("burpsuite")
        execution_module.BURP_REQUEST_OBJECT = execution_module.BurpRequest(
            args.request
        )
        logger.info("Use Burpsuite request as base.")
    elif args.module:
        logger.info(f"Use provided module: '{args.module}'.")
        module_path_obj = Path(args.module)

        if not module_path_obj.exists():
            logger.error(f"The specified file does not exist.")
            return 1

        if module_path_obj.suffix != ".py":
            logger.error("The specified file is not a Python module 🐍.")
            return 1

        execution_module = loader.load_module(module_path=module_path_obj)
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

        if args.fifo and command_executor.target.os == "unix":
            logger.info(
                "🤏 Making your dumb shell semi-interactive using 'fifo' action."
            )
            remote_terminal.start_named_pipe(
                action_class=command_executor.action_manager.get_action("fifo"),
                read_interval=args.read_interval,
                command_in=args.stdin,
                command_out=args.stdout,
            )

        remote_terminal.start()
    except Exception as exc:
        error_trace = traceback.format_exc()
        logger.error(f"Unhandled exception occurred: {exc}\n{error_trace}")

    logger.success("Toboggan execution completed.")
