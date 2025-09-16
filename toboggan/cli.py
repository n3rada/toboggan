"""
Toboggan Console Entry Point

This module serves as the main entry point for the Toboggan framework,
responsible for parsing CLI arguments, loading execution modules, and
launching the interactive remote terminal environment.

Features:
- Supports command execution via wrappers, HTTP requests, or modules.
- Enables FIFO-based semi-interactive remote shells.
- Configures proxy settings for module compatibility.
- Provides user-friendly logging and help output.
"""

# Built-in imports
import argparse
import os
import time
from pathlib import Path

# External library imports
from modwrap import ModuleWrapper
import httpx

# Local library imports
from toboggan.core import logbook
from toboggan.core import executor
from toboggan.core import terminal
from toboggan.utils import methods
from toboggan.utils import banner
from toboggan import __version__ as version

# Directory where built-in handlers are stored
BUILTIN_DIR = Path(__file__).parent / "core/handlers"

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="toboggan",
        add_help=True,
        description="Bring intelligence to any remote command execution (RCE) vector.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""\nExample usage:\n    - toboggan -m rce.py --os linux --camouflage\n\nFor more information, visit: https://github.com/n3rada/toboggan\n\nVersion: {version}""",
        allow_abbrev=True,
        exit_on_error=True,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
        help="Show Toboggan version and exit.",
    )

    parser.add_argument(
        "--proxy",
        type=str,
        nargs="?",
        const="http://127.0.0.1:8080",
        help="Set HTTP(S) proxy, e.g. 'http://127.0.0.1:8080'. Default is Burp Suite proxy.",
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
        help=(
            "Specify the shell binary to be used for named pipe execution (e.g., /bin/sh, /bin/bash)"
        ),
    )

    execution_group.add_argument(
        "-b64",
        "--base64",
        action="store_true",
        required=False,
        help="Base64-encode every command before execution.",
    )

    execution_group.add_argument(
        "--camouflage",
        action="store_true",
        required=False,
        help="Wrap the command using a hide/unhide action to evade detection.",
    )

    source_group = execution_group.add_mutually_exclusive_group(required=True)

    source_group.add_argument(
        "--exec-wrapper",
        type=str,
        help="Shell command template with placeholder ||cmd|| (e.g., 'sh -c \"||cmd||\"').",
    )
    source_group.add_argument(
        "-r",
        "--request",
        type=str,
        help="Burp request template file with placeholder ||cmd||.",
    )
    source_group.add_argument(
        "-m",
        "--module",
        type=str,
        help="Python module implementing the 'execute(command, timeout)' function.",
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

    system_group.add_argument(
        "--os",
        type=str,
        choices=["linux", "windows"],
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
        "--debug",
        action="store_true",
        required=False,
        help="Enable debug logging mode.",
    )
    return parser.parse_args()

def main() -> int:
   
    # Parse arguments
    args = parse_arguments()

    print(banner.show())

    env = os.environ

    # Set log level to DEBUG if --debug is passed
    if args.debug:
        env["LOG_LEVEL"] = "DEBUG"

    logger = logbook.get_logger()

    if args.proxy:
        if not methods.is_valid_proxy(args.proxy):
            logger.warning("⚠️ Provided proxy may be malformed or unsupported.")
            return 1

        os.environ["http_proxy"] = args.proxy
        os.environ["https_proxy"] = args.proxy
        os.environ["HTTP_PROXY"] = args.proxy
        os.environ["HTTPS_PROXY"] = args.proxy
        os.environ["ALL_PROXY"] = args.proxy
        os.environ["all_proxy"] = args.proxy

        logger.info(f"🌐 Proxy set to {args.proxy}")

    public_ip = None
    try:
        with httpx.Client(verify=False, http1=True, http2=False) as client:
            start_time = time.perf_counter()
            response = client.get("https://api.ipify.org?format=json", timeout=15)
            end_time = time.perf_counter()

            rtt = end_time - start_time

            if response.status_code == 200:
                public_ip = response.json().get("ip", None)

    except httpx.TimeoutException:
        logger.error("Request timed-out.")
    except Exception as e:
        logger.warning(f"⚠️ Error retrieving public IP: {e}")

    if public_ip is None:
        return 1

    logger.info(f"🌍 Public IP: {public_ip} (⏱️ RTT: {rtt:.2f}s)")

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
            shell=args.shell,
            target_os=args.os,
            base64_wrapping=args.base64,
            camouflage=args.camouflage,
        )
    except RuntimeError:
        return 1

    logger.info(
        f"🛝 It takes about {command_executor.avg_response_time:.2f}s for a command "
        f"to slide down the toboggan 🎯"
    )

    try:
        remote_terminal = terminal.Terminal(executor=command_executor)

        if command_executor.target.os == "linux":
            if args.fifo:
                logger.info(
                    "🤏 Making your dumb shell semi-interactive using 'fifo' action."
                )
                command_executor.os_helper.start_named_pipe(
                    action_class=command_executor.action_manager.get_action("fifo"),
                    read_interval=args.read_interval,
                    command_in=args.stdin,
                    command_out=args.stdout,
                )

        remote_terminal.start()
    except Exception:
        logger.exception("Unhandled exception occurred")
        return 1

    logger.success("Toboggan execution completed.")
    return 0
