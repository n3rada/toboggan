import threading
import time
import random

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import NamedPipe


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

        # Start the background process and capture its PID
        # Using sh -c to wrap the pipeline and echo the PID
        full_cmd = f"{tail_cmd}|{self._shell} > {self._stdout} 2>&1 & echo $!"
        result = self._executor.remote_execute(full_cmd)

        # Extract PID from the output
        try:
            self.__fifo_pid = result.strip()
            if self.__fifo_pid and self.__fifo_pid.isdigit():
                logger.info(
                    f"🔢 FIFO background process started with PID: {self.__fifo_pid}"
                )
            else:
                logger.warning(f"⚠️ Could not capture FIFO PID, got: {result!r}")
                self.__fifo_pid = None
        except Exception as e:
            logger.warning(f"⚠️ Failed to capture FIFO PID: {e}")
            self.__fifo_pid = None

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

        # Kill the specific FIFO background process using kill command
        if hasattr(self, "_FifoAction__fifo_pid") and self.__fifo_pid:
            logger.info(f"🔪 Killing FIFO process with PID: {self.__fifo_pid}")
            kill_path = self._executor.os_helper.get_command_location("kill")

            if kill_path:
                try:
                    # Try graceful termination first (SIGTERM)
                    self._executor.remote_execute(
                        f"{kill_path} {self.__fifo_pid}", debug=False
                    )
                    logger.success(f"✅ Killed FIFO process (PID: {self.__fifo_pid})")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to kill PID {self.__fifo_pid} with SIGTERM: {e}"
                    )

                    # Try forceful kill (SIGKILL)
                    try:
                        self._executor.remote_execute(
                            f"{kill_path} -9 {self.__fifo_pid}", debug=False
                        )
                        logger.success(
                            f"✅ Force killed FIFO process (PID: {self.__fifo_pid})"
                        )
                    except Exception as e2:
                        logger.error(
                            f"❌ Failed to force kill PID {self.__fifo_pid}: {e2}"
                        )
            else:
                logger.warning("⚠️ Could not find 'kill' command")
        else:
            logger.warning("⚠️ No FIFO PID available, cannot kill specific process")

        # Clean up FIFO files
        logger.info("🧹 Cleaning up FIFO files")
        rm_path = self._executor.os_helper.get_command_location("rm")

        if rm_path:
            # Remove stdin FIFO
            try:
                self._executor.remote_execute(
                    f"{rm_path} -f {self._stdin}", debug=False
                )
                logger.debug(f"✅ Removed stdin FIFO: {self._stdin}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to remove stdin FIFO {self._stdin}: {e}")

            # Remove stdout FIFO
            try:
                self._executor.remote_execute(
                    f"{rm_path} -f {self._stdout}", debug=False
                )
                logger.debug(f"✅ Removed stdout FIFO: {self._stdout}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to remove stdout FIFO {self._stdout}: {e}")
        else:
            logger.warning("⚠️ Could not find 'rm' command to clean up FIFO files")

    def execute(self, command: str):
        echo_path = self._executor.os_helper.get_command_location("echo")
        forward_command = f"{echo_path} '{command}' > {self._stdin}"

        self._executor.remote_execute(forward_command)

    def __poll_output(self) -> None:

        cat_path = self._executor.os_helper.get_command_location("cat")
        sed_path = self._executor.os_helper.get_command_location("sed")
        tail_path = self._executor.os_helper.get_command_location("tail")
        dd_path = self._executor.os_helper.get_command_location("dd")

        poll_commands = [
            f"{cat_path} {self._stdout} && > {self._stdout}",
            f"{sed_path} -n p {self._stdout} && > {self._stdout}",
            f"{tail_path} -n +1 {self._stdout} && > {self._stdout}",
            f"{dd_path} if={self._stdout} bs=4096 2>/dev/null && > {self._stdout}",
        ]

        while not self.__stop_thread:

            # Apply jitter to avoid burst collisions
            time.sleep(random.uniform(self._read_interval, self._read_interval * 1.3))

            # Simplest: read and truncate in one command using shell redirection
            stdout_output = self._executor.remote_execute(
                random.choice(poll_commands),
                debug=False,
            )

            if stdout_output:
                if self.tty:
                    print(stdout_output, end="", flush=True)
                    continue

                if self._executor.os_helper.is_shell_prompt_in(stdout_output):
                    self.tty = True
                    print(stdout_output, end=" ", flush=True)
                else:
                    self.tty = False
                    print(stdout_output)
