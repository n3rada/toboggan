# Built-in imports
import argparse
import os
import sys
import time
from pathlib import Path

# External library imports
from loguru import logger
from modwrap import ModuleWrapper
import httpx

# Local library imports
from toboggan import __version__
from toboggan.src.utils import logbook
from toboggan.src import executor
from toboggan.src import terminal
from toboggan.src.utils import common
from toboggan.src.utils import banner

# Directory where built-in handlers are stored
BUILTIN_DIR = Path(__file__).parent / "core/handlers"


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="toboggan",
        add_help=True,
        description="Bring intelligence to any remote command execution (RCE) vector.",
        epilog=f"""\nExample usage:\n    - toboggan -m rce.py --os linux --camouflage\n\nFor more information, visit: https://github.com/n3rada/toboggan""",
        allow_abbrev=True,
        exit_on_error=True,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )

    parser.add_argument(
        "--proxy",
        type=str,
        nargs="?",
        const="http://127.0.0.1:8080",
        help="Set HTTP(S) proxy, e.g. 'http://127.0.0.1:8080'. Default is Burp Suite proxy.",
    )

    parser.add_argument(
        "--history",
        action="store_true",
        required=False,
        default=False,
        help="Enable persistent command history (stored in temporary folder).",
    )

    execution_group = parser.add_argument_group(
        "Execution Configuration", "Options to configure how commands are executed."
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
    named_pipe_group = parser.add_argument_group(
        "Named Pipe Settings", "Options to manage named pipe."
    )

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
        default=0.3,
        help="Interval (in seconds) for reading output from the named pipe.",
    )

    named_pipe_group.add_argument(
        "-i",
        "--stdin",
        type=str,
        default=None,
        help="Input path (file or directory) for FIFO where commands go. If directory, filename will be auto-generated.",
    )

    named_pipe_group.add_argument(
        "-o",
        "--stdout",
        type=str,
        default=None,
        help="Output path (file or directory) for FIFO where command output appears. If directory, filename will be auto-generated.",
    )

    system_group = parser.add_argument_group(
        "System Configuration", "Specify the target operating system."
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
        help="Specify the target working directory (must be an absolute path to a directory).",
    )
    system_group.add_argument(
        "--paths",
        type=str,
        nargs="+",
        default=None,
        required=False,
        help="Custom paths to search for commands (e.g., /opt/bin /usr/local/bin). These are checked before standard detection methods.",
    )
    system_group.add_argument(
        "--path",
        type=str,
        default=None,
        required=False,
        help="Custom PATH string with colon-separated directories (e.g., /opt/bin:/usr/local/bin:/custom/path). These are checked before standard detection methods.",
    )

    advanced_group = parser.add_argument_group(
        "Advanced Options", "Additional advanced or debugging options."
    )

    advanced_group.add_argument(
        "--prefix",
        type=str,
        default="!",
        help="Command prefix to use actions in the terminal session.",
    )

    advanced_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shortcut for --log-level DEBUG).",
    )

    advanced_group.add_argument(
        "--trace",
        action="store_true",
        help="Enable TRACE logging (shortcut for --log-level TRACE).",
    )

    advanced_group.add_argument(
        "--log-level",
        type=str,
        choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Set the logging level explicitly.",
    )

    return parser


def main() -> int:

    print(banner.display_banner())

    parser = build_parser()
    args = parser.parse_args()

    # Show help if no cli args provided
    if len(sys.argv) <= 1:
        parser.print_help()
        return 1

    # Determine log level: --log-level takes precedence, then --debug, then --trace, then default INFO
    if args.log_level:
        log_level = args.log_level
    elif args.debug:
        log_level = "DEBUG"
    elif args.trace:
        log_level = "TRACE"
    else:
        log_level = "INFO"

    logbook.setup_logging(level=log_level)

    if args.proxy:
        if not args.proxy.startswith(("http://", "https://")):
            logger.error("Invalid proxy format.")
            return 1

        for k in [
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "all_proxy",
        ]:
            os.environ[k] = args.proxy

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

        if not wrapper.has_args("execute", ["command", "timeout"]):
            logger.error(
                "Provided module does not implement required 'execute(command, timeout)' function."
            )
            return 1

        # Verify that the module can be imported correctly
        deps = wrapper.get_dependencies()
        if deps["missing"]:
            logger.error(
                f"Cannot import module due to missing dependencies: {', '.join(deps['missing'])}"
            )
            logger.warning(
                "Inject the dependencies or install toboggan using pipx with --system-site-packages"
            )
            return 1

        execution_module = wrapper.module

    else:
        logger.error("No module provided. I cannot slide on anything.")
        return 1

    if args.base64:
        logger.info("🔐 Base64 encoding enabled for all commands.")

    # Validate working directory if provided
    if args.working_directory:
        if not common.is_valid_directory_path(args.working_directory):
            logger.error(f"❌ Invalid working directory path: {args.working_directory}")
            return 1

    # Merge --path and --paths arguments
    custom_paths = []
    if args.path:
        # Split colon-separated PATH string
        custom_paths.extend([p.strip() for p in args.path.split(":") if p.strip()])
        logger.info(f"📂 Parsed --path: {', '.join(custom_paths)}")

    if args.paths:
        # Add space-separated paths
        custom_paths.extend(args.paths)
        logger.info(f"📂 Added --paths: {', '.join(args.paths)}")

    # Remove duplicates while preserving order
    if custom_paths:
        seen = set()
        unique_paths = []
        for path in custom_paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        custom_paths = unique_paths

    try:
        command_executor = executor.Executor(
            execute_method=execution_module.execute,
            working_directory=args.working_directory,
            shell=args.shell,
            target_os=args.os,
            base64_wrapping=args.base64,
            camouflage=args.camouflage,
            custom_paths=custom_paths if custom_paths else None,
        )
    except RuntimeError:
        return 1

    logger.info(
        f"🛝 It takes about {command_executor.avg_response_time:.2f}s for a command "
        f"to slide down the toboggan 🎯"
    )

    # Validate and set stdin/stdout paths if provided
    if args.stdin:
        if common.is_valid_file_path(args.stdin):
            # It's a file path
            logger.info(f"📄 Using FIFO stdin file path: {args.stdin}")
            command_executor.os_helper.stdin_path = args.stdin
        elif common.is_valid_directory_path(args.stdin):
            # It's a directory, generate filename
            base_dir = args.stdin.rstrip("/")
            file_name = common.generate_uuid()
            stdin_path = f"{base_dir}/{file_name}"
            command_executor.os_helper.stdin_path = stdin_path
            logger.info(f"📝 Generated FIFO stdin path: {stdin_path}")
        else:
            logger.error(f"❌ Invalid stdin path: {args.stdin}")
            return 1

    if args.stdout:
        if common.is_valid_file_path(args.stdout):
            # It's a file path
            logger.info(f"📄 Using FIFO stdout file path: {args.stdout}")
            command_executor.os_helper.stdout_path = args.stdout
        elif common.is_valid_directory_path(args.stdout):
            # It's a directory, generate filename
            base_dir = args.stdout.rstrip("/")
            file_name = common.generate_uuid()
            stdout_path = f"{base_dir}/{file_name}"
            command_executor.os_helper.stdout_path = stdout_path
            logger.info(f"📝 Generated FIFO stdout path: {stdout_path}")
        else:
            logger.error(f"❌ Invalid stdout path: {args.stdout}")
            return 1

    try:
        remote_terminal = terminal.Terminal(
            executor=command_executor,
            prefix=args.prefix,
            history=args.history,
            log_level=log_level,
        )

        if args.fifo:
            logger.info(
                "🤏 Making your dumb shell semi-interactive using 'fifo' action."
            )

            fifo_action = command_executor.action_manager.get_action("fifo")

            if fifo_action is None:
                logger.error("❌ FIFO action is not available for the target OS.")
                return 1

            command_executor.os_helper.start_named_pipe(
                action_class=fifo_action,
                read_interval=args.read_interval,
            )

        return remote_terminal.start()
    except Exception:
        logger.exception("Unhandled exception occurred")
        return 1

    return 0
