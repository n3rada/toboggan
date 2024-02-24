# Local library imports
from toboggan.src import commands

# Third party library imports
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import ThreadedAutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.history import ThreadedHistory, InMemoryHistory
from prompt_toolkit.cursor_shapes import CursorShape


class Shell:
    def __init__(
        self,
        commands: "commands.Commands",
        interactive: bool = False,
        read_interval: float = 0.4,
        session_identifier: str = None,
    ):
        self.__prompt_session = PromptSession(
            cursor=CursorShape.BLINKING_BEAM,
            multiline=False,
            enable_history_search=True,
            wrap_lines=True,
            auto_suggest=ThreadedAutoSuggest(auto_suggest=AutoSuggestFromHistory()),
            history=ThreadedHistory(history=InMemoryHistory()),
        )

        self.__commands = commands

        if interactive:
            self.__commands.start_interactivity(
                read_interval=read_interval, session_identifier=session_identifier
            )

    # Public methods
    def start(self) -> None:
        result = None
        user_input = ""
        keyboard_interruption = 0
        while True:
            try:
                user_input = self.__prompt_session.prompt(
                    message=self.__commands.get_prompt()
                )
                if not user_input:
                    continue
            except KeyboardInterrupt:
                if keyboard_interruption == 3:
                    print(f"[Toboggan] Emergency exit received. ")
                    self.__commands.terminate()
                keyboard_interruption += 1
                print(
                    f"[Toboggan] Keyboard interruption received. Not exiting.",
                    flush=True,
                )
                continue
            except Exception as excep:
                print(f"[Toboggan] Exception occured: {excep}")
                continue
            else:
                keyboard_interruption = 0
                if result := self.__commands.handle(command=user_input):
                    print(result, end="", flush=True)
