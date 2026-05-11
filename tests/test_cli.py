# tests/test_cli.py

import pytest
from toboggan.cli import build_parser


class TestBuildParser:
    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_parser_prog(self, parser):
        assert parser.prog == "toboggan"

    def test_version_action(self, parser):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_module_positional(self, parser):
        args = parser.parse_args(["exploit.py"])
        assert args.module == "exploit.py"

    def test_exec_wrapper(self, parser):
        args = parser.parse_args(["--exec-wrapper", 'curl "||cmd||"'])
        assert args.exec_wrapper == 'curl "||cmd||"'
        assert args.module is None

    def test_request_flag(self, parser):
        args = parser.parse_args(["-r", "burp_request.xml"])
        assert args.request == "burp_request.xml"

    def test_proxy_default(self, parser):
        # nargs="?" means --proxy alone uses the const, but --proxy <value> uses <value>
        args = parser.parse_args(["--proxy", "--", "exploit.py"])
        assert args.proxy == "http://127.0.0.1:8080"

    def test_proxy_custom(self, parser):
        args = parser.parse_args(["--proxy", "http://10.0.0.1:3128", "exploit.py"])
        assert args.proxy == "http://10.0.0.1:3128"

    def test_fifo_flag(self, parser):
        args = parser.parse_args(["--fifo", "exploit.py"])
        assert args.fifo is True

    def test_base64_flag(self, parser):
        args = parser.parse_args(["-b64", "exploit.py"])
        assert args.base64 is True

    def test_obfuscate_flag(self, parser):
        args = parser.parse_args(["-O", "exploit.py"])
        assert args.obfuscate is True

    def test_os_choices(self, parser):
        args = parser.parse_args(["--os", "linux", "exploit.py"])
        assert args.os == "linux"

        args = parser.parse_args(["--os", "windows", "exploit.py"])
        assert args.os == "windows"

    def test_os_invalid_choice(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["--os", "macos", "exploit.py"])

    def test_log_level_choices(self, parser):
        for level in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            args = parser.parse_args(["--log-level", level, "exploit.py"])
            assert args.log_level == level

    def test_debug_flag(self, parser):
        args = parser.parse_args(["--debug", "exploit.py"])
        assert args.debug is True

    def test_trace_flag(self, parser):
        args = parser.parse_args(["--trace", "exploit.py"])
        assert args.trace is True

    def test_history_flag(self, parser):
        args = parser.parse_args(["--history", "exploit.py"])
        assert args.history is True

    def test_prefix_default(self, parser):
        args = parser.parse_args(["exploit.py"])
        assert args.prefix == "!"

    def test_prefix_custom(self, parser):
        args = parser.parse_args(["--prefix", "/", "exploit.py"])
        assert args.prefix == "/"

    def test_read_interval_default(self, parser):
        args = parser.parse_args(["exploit.py"])
        assert args.read_interval == 0.3

    def test_stdin_stdout_paths(self, parser):
        args = parser.parse_args(["-i", "/tmp/in", "-o", "/tmp/out", "exploit.py"])
        assert args.stdin == "/tmp/in"
        assert args.stdout == "/tmp/out"

    def test_working_directory(self, parser):
        args = parser.parse_args(["-wd", "/opt/work", "exploit.py"])
        assert args.working_directory == "/opt/work"

    def test_paths_multiple(self, parser):
        # nargs="+" consumes all following args, so module must come first
        args = parser.parse_args(["exploit.py", "--paths", "/opt/bin", "/usr/local/bin"])
        assert args.paths == ["/opt/bin", "/usr/local/bin"]

    def test_path_colon_separated(self, parser):
        args = parser.parse_args(["--path", "/opt/bin:/usr/local/bin", "exploit.py"])
        assert args.path == "/opt/bin:/usr/local/bin"

    def test_shell_option(self, parser):
        args = parser.parse_args(["--shell", "/bin/bash", "exploit.py"])
        assert args.shell == "/bin/bash"

    def test_exec_wrapper_and_request_mutually_exclusive(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["--exec-wrapper", "cmd", "-r", "file"])

    def test_no_args_defaults(self, parser):
        args = parser.parse_args(["exploit.py"])
        assert args.module == "exploit.py"
        assert args.proxy is None
        assert args.fifo is False
        assert args.base64 is False
        assert args.obfuscate is False
        assert args.debug is False
        assert args.trace is False
        assert args.history is False
        assert args.os is None
        assert args.shell is None
        assert args.working_directory is None
        assert args.log_level is None
