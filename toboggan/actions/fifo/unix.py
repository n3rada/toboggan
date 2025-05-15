# Built-in imports
import threading
import time
import random

# Local application/library specific imports
from toboggan.core.action import NamedPipe


class FifoAction(NamedPipe):

    DESCRIPTION = "Provides semi-interactivity using named pipes (FiFo) for remote command execution."

    def __init__(
        self,
        executor,
        read_interval=0.4,
        command_in=None,
        command_out=None,
    ):
        super().__init__(executor, read_interval, command_in, command_out)
        self.tty = False

    def setup(self):
        self._executor.remote_execute(f"/bin/mkfifo {self._stdin}")

        shell = "$(command -v $0)"

        self._executor.remote_execute(
            f"/bin/tail -f {self._stdin}|{shell} > {self._stdout} 2>&1 &"
        )

        # Initialize stop flag
        self.__stop_thread = False

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
        self._executor.remote_execute(command=f"/bin/echo '{command}' > {self._stdin}")

    def __poll_output(self) -> None:

        poll_commands = [
            f"/usr/bin/sed -n p {self._stdout}; : > {self._stdout}",
            f"/usr/bin/tail -n +1 {self._stdout}; : > {self._stdout}",
            f"/usr/bin/dd if={self._stdout} bs=4096 2>/dev/null; : > {self._stdout}",
        ]

        while not self.__stop_thread:

            time.sleep(random.uniform(self._read_interval, self._read_interval * 1.5))

            command_output = self._executor.remote_execute(
                random.choice(poll_commands),
                debug=False,
            )

            if command_output:
                if self.tty:
                    print(command_output, end="", flush=True)
                    continue

                if self._executor.os_helper.is_shell_prompt_in(command_output):
                    self.tty = True
                    print(command_output, end=" ", flush=True)
                else:
                    self.tty = False
                    print(command_output)
