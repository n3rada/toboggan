import threading
import time
import random

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.action import NamedPipe


class FifoAction(NamedPipe):

    DESCRIPTION = "Provides semi-interactivity using named pipes (FiFo) for remote command execution."

    def __init__(
        self,
        executor,
        read_interval: float = 0.4,
    ):
        # Get stdin/stdout from os_helper
        stdin_path = executor.os_helper.stdin_path
        stdout_path = executor.os_helper.stdout_path

        super().__init__(executor, read_interval, stdin_path, stdout_path)

        self.tty = False

        self._shell = self._executor.shell

        logger.info(f"🌀 FiFo will use shell: {self._shell}")

    def setup(self):
        mkfifo_path = self._executor.os_helper.get_command_location("mkfifo")
        mkfifo_cmd = f"{mkfifo_path} {self._stdin}"
        self._executor.remote_execute(mkfifo_cmd)

        tail_path = self._executor.os_helper.get_command_location("tail")
        tail_cmd = f"{tail_path} -f {self._stdin}"
        full_cmd = f"{tail_cmd}|{self._shell} > {self._stdout} 2>&1 &"
        self._executor.remote_execute(full_cmd)

        self.__stop_thread = False
        self.__read_thread = None

    def run(self):
        self.__read_thread = threading.Thread(
            name="output_polling",
            target=self.__poll_output,
            args=(),
            daemon=True,
        )
        self.__read_thread.start()

    def _stop(self):
        self.__stop_thread = True
        if self.__read_thread is not None:
            self.__read_thread.join()

    def execute(self, command: str):
        echo_path = self._executor.os_helper.get_command_location("echo")
        forward_command = f"{echo_path} '{command}' > {self._stdin}"

        self._executor.remote_execute(forward_command)

    def __poll_output(self) -> None:

        sed_path = self._executor.os_helper.get_command_location("sed")
        tail_path = self._executor.os_helper.get_command_location("tail")
        dd_path = self._executor.os_helper.get_command_location("dd")

        poll_commands = [
            f"{sed_path} -n p {self._stdout}; : > {self._stdout}",
            f"{tail_path} -n +1 {self._stdout}; : > {self._stdout}",
            f"{dd_path} if={self._stdout} bs=4096 2>/dev/null; : > {self._stdout}",
        ]

        while not self.__stop_thread:

            # Apply jitter to avoid burst collisions
            time.sleep(random.uniform(self._read_interval, self._read_interval * 1.5))

            stdout_pathput = self._executor.remote_execute(
                random.choice(poll_commands),
                debug=False,
            )

            if stdout_pathput:
                if self.tty:
                    print(stdout_pathput, end="", flush=True)
                    continue

                if self._executor.os_helper.is_shell_prompt_in(stdout_pathput):
                    self.tty = True
                    print(stdout_pathput, end=" ", flush=True)
                else:
                    self.tty = False
                    print(stdout_pathput)
