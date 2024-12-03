#!/usr/bin/env python3

# Built-in imports
import argparse
import sys
import re

# Local library imports
from toboggan.src import terminal, target, executor, commands


def banner() -> None:
    print(
        r"""
            _____      _
           /__   \___ | |__   ___   __ _  __ _  __ _ _ __
             / /\/ _ \| '_ \ / _ \ / _` |/ _` |/ _` | '_ \
            / / | (_) | |_) | (_) | (_| | (_| | (_| | | | |
            \/   \___/|_.__/ \___/ \__, |\__, |\__,_|_| |_|
                                    |___/ |___/
             Remote command execution module wrapping tool.
                              @n3rada
    """
    )


def run() -> None:
    parser = argparse.ArgumentParser(
        prog="toboggan",
        add_help=True,
        description="A Python module wrapper for RCEs that can be leveraged to an interactive shell.",
    )

    # Argument Groups
    module_group = parser.add_argument_group(
        "Module Configuration", "Options to configure the execution module."
    )
    request_group = parser.add_argument_group(
        "Request Configuration", "Options for crafting and sending requests."
    )
    interactive_group = parser.add_argument_group(
        "Interactive Settings", "Options to manage interactive sessions."
    )
    advanced_group = parser.add_argument_group(
        "Advanced Options", "Additional advanced or debugging options."
    )

    # Module configuration arguments
    module_group.add_argument(
        "-m",
        "--module",
        type=str,
        default=None,
        help="Module path to be imported and executed or built-in module name.",
    )
    module_group.add_argument(
        "-o",
        "--os",
        type=str,
        default=None,
        help="OS command with placeholder ||cmd||.",
    )

    # Request configuration arguments
    request_group.add_argument(
        "-u",
        "--url",
        type=str,
        default=None,
        help="URL to use if a built-in module is specified. Replace ||URL|| placeholder.",
    )
    request_group.add_argument(
        "--post",
        action="store_true",
        required=False,
        help="Specify that the URL request should be a POST request (only with -u/--url).",
    )
    request_group.add_argument(
        "-p",
        "--params",
        nargs="*",
        help="Additional parameters as key=value pairs.",
    )
    request_group.add_argument(
        "--cmd-param",
        type=str,
        default="cmd",
        help="Specify the name of the command parameter (e.g., cmd, command, c).",
    )

    # Interactive session arguments
    interactive_group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        required=False,
        help="Start an interactive session.",
    )
    interactive_group.add_argument(
        "-s",
        "--session",
        required=False,
        type=str,
        default=None,
        help="Session to connect.",
    )
    interactive_group.add_argument(
        "-r",
        "--read-interval",
        required=False,
        type=float,
        default=None,
        help="Reading interval for interactivity.",
    )

    # Advanced options
    advanced_group.add_argument(
        "-a",
        "--alias-prefix",
        required=False,
        type=str,
        default=None,
        help="Desired alias prefix to use.",
    )
    advanced_group.add_argument(
        "-c",
        "--clear-commands",
        action="store_true",
        required=False,
        help="Send unobfuscated commands.",
    )
    advanced_group.add_argument(
        "-b",
        "--burp",
        action="store_true",
        required=False,
        help="Pass the traffic through Burp Suite if '# ||BURP||' placeholder is present in the module.",
    )

    # Parse arguments
    args = parser.parse_args()

    # Add validation for grouped arguments
    if args.url:
        if not args.params and not args.cmd_param:
            parser.error(
                "URL-based execution requires parameters (--params) or a command parameter (--cmd-param)."
            )
        if args.post and not args.url:
            parser.error("The --post argument can only be used with --url.")

    if args.session and not args.interactive:
        parser.error("The --session argument requires --interactive.")

    if args.read_interval and not args.interactive:
        parser.error("The --read-interval argument requires --interactive.")

    # Parse parameters
    request_parameters = {}
    if args.params:
        for param in args.params:
            if "=" in param:
                key, value = param.split("=", 1)
                request_parameters[key] = value
            else:
                parser.error(f"Invalid parameter format: {param}. Use key=value.")

    # Module handling
    module_path_or_name = args.module
    if args.os:
        module_path_or_name = "snippet"
    elif args.url:
        module_path_or_name = "webshell__"
        module_path_or_name += "POST" if args.post else "GET"

    # Load the module
    module_instance = executor.Module(
        module_path=module_path_or_name,
        url=args.url,
        request_parameters=request_parameters,
        command_parameter=args.cmd_param,
        burp_proxy=args.burp,
    )

    if args.os is not None:
        module_instance.module.BASE_CMD = args.os

    # Define an executor
    executor_instance = executor.Executor(module=module_instance)

    if args.clear_commands:
        print("[Toboggan] Clear text mode activated.")
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
