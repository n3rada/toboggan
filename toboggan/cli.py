#!/usr/bin/env python3

# Built-in imports
import argparse
import sys
import re

# Local library imports
from toboggan.src import terminal, target, executor, commands


def banner() -> None:
    banner = rf"""
            _____      _
           /__   \___ | |__   ___   __ _  __ _  __ _ _ __
             / /\/ _ \| '_ \ / _ \ / _` |/ _` |/ _` | '_ \
            / / | (_) | |_) | (_) | (_| | (_| | (_| | | | |
            \/   \___/|_.__/ \___/ \__, |\__, |\__,_|_| |_|
                                    |___/ |___/
             Remote command execution module wrapping tool.
                              @n3rada
    """
    print(banner)


def console() -> None:
    parser = argparse.ArgumentParser(
        prog="toboggan",
        add_help=True,
        description="A python3 module wrapper for your RCEs that can be leveraged to an interactive shell.",
    )

    parser.add_argument(
        "-m",
        "--module",
        type=str,
        default=None,
        help="Module path to be imported and executed or built-in module name.",
    )

    parser.add_argument(
        "-o",
        "--os",
        type=str,
        default=None,
        help="OS command with placeholder ||cmd||.",
    )

    parser.add_argument(
        "-u",
        "--url",
        type=str,
        default=None,
        help="URL to use if a built-in module is specified. Replace ||URL|| placeholder.",
    )

    parser.add_argument(
        "-p",
        "--password",
        type=str,
        default=None,
        help="Password in 'key=value' format. If only value is provided, a default key 'ps' will be used.",
    )

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        required=False,
        help="Start an interactive session.",
    )
    parser.add_argument(
        "-s",
        "--session",
        required=False,
        type=str,
        default=None,
        help="Session to connect.",
    )
    parser.add_argument(
        "-r",
        "--read-interval",
        required=False,
        type=float,
        default=None,
        help="Reading interval for interactivity.",
    )
    parser.add_argument(
        "-a",
        "--alias-prefix",
        required=False,
        type=str,
        default=None,
        help="Desired alias prefix to use.",
    )
    parser.add_argument(
        "-c",
        "--clear-commands",
        action="store_true",
        required=False,
        help="Send unobfuscated commands.",
    )

    parser.add_argument(
        "-b",
        "--burp",
        action="store_true",
        required=False,
        help="Pass the traffic through burp if '# ||BURP||' placeholder is present inside choosen module.",
    )

    banner()

    args = parser.parse_args()

    if ("-h" in sys.argv or "--help" in sys.argv) or (
        args.module is None and args.url is None and args.os is None
    ):
        parser.print_help()
        return

    # Check for the presence of '-i' when '-s' or '-r' is specified
    if (args.session or args.read_interval) and not args.interactive:
        parser.error("[Toboggan] The -s and -r arguments require the -i (interactive) argument.")


    password_param = None
    password_content = None

    if args.password:
        # Try the formats `"key"="value"` or `'key'='value'`
        if match := re.match(r'["\']?(.*?)["\']?=["\']?(.*?)["\']?$', args.password):
            password_param, password_content = match.groups()
        else:
            # Try the second format `key=value`
            password_parts = args.password.split("=", 1)
            if len(password_parts) == 2:
                password_param, password_content = password_parts
            else:
                password_param = "ps"
                password_content = password_parts[0]

    module_path_or_name = args.module
    if args.os:
        module_path_or_name = "snippet"
    elif args.url:
        module_path_or_name = "webshell"

    # Load the module
    module_instance = executor.Module(
        module_path=module_path_or_name,
        url=args.url,
        password_param=password_param,
        password_content=password_content,
        burp_proxy=args.burp,
    )

    if args.os is not None:
        module_instance.module.BASE_CMD = args.os

    # Define an executor
    executor_instance = executor.Executor(module=module_instance)

    if args.clear_commands:
        print(f"[Toboggan] Clear text mode activated.")
        executor_instance.obfuscation = False

    # You can instanciate a target that implement the Executor
    target_instance = target.Target(command_executor=executor_instance)
    # Thus, instanciate a Command class that implement the Target one's
    commands_instance = commands.Commands(
        target=target_instance, prefix=args.alias_prefix
    )

    # Finally, you can create a Shell object that implement the Commands instance
    remote_shell = terminal.Shell(
        commands=commands_instance,
        interactive=(args.session or args.interactive),
        read_interval=args.read_interval,
        session_identifier=args.session,
    )

    # And start-it
    remote_shell.start()
