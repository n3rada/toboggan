import threading
import time
import random

from toboggan.core.action import NamedPipe


class FifoAction(NamedPipe):

    DESCRIPTION = "Provides semi-interactivity using named pipes (FiFo) for remote command execution."

    def __init__(
        self,
        executor,
        read_interval=0.4,
        command_in=None,
        command_out=None,
        shell=None,
    ):
        super().__init__(executor, read_interval, command_in, command_out)

        self.__os_helper = executor.os_helper
        self.__os_helper.is_busybox_present  # Force BusyBox detection

        if shell is None:
            self.__shell = "$(command -v $0)"
        else:
            self.__shell = shell.strip()

        self._logger.info(f"Using shell: {self.__shell}")
        self.tty = False

    def setup(self):
        # Use busybox-wrapped mkfifo
        mkfifo_cmd = self.__os_helper.busybox_wrap(f"mkfifo {self._stdin}")
        self._executor.remote_execute(mkfifo_cmd)

        # Use busybox-wrapped tail
        tail_cmd = self.__os_helper.busybox_wrap(f"tail -f {self._stdin}")
        full_cmd = f"{tail_cmd}|{self.__shell} > {self._stdout} 2>&1 &"
        self._executor.remote_execute(full_cmd)

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
        echo_cmd = self.__os_helper.busybox_wrap(f"echo '{command}' > {self._stdin}")
        self._executor.remote_execute(echo_cmd)

    def __poll_output(self) -> None:
        # BusyBox-friendly polling commands
        poll_commands = [
            self.__os_helper.busybox_wrap(
                f"sed -n p {self._stdout}; : > {self._stdout}"
            ),
            self.__os_helper.busybox_wrap(
                f"tail -n +1 {self._stdout}; : > {self._stdout}"
            ),
            self.__os_helper.busybox_wrap(
                f"dd if={self._stdout} bs=4096 2>/dev/null; : > {self._stdout}"
            ),
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
