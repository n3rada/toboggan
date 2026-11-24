# toboggan/core/utils/navigator.py

"""Reusable full-screen navigator that fetches nested data on demand.

The navigator never dumps a whole tree up front. It asks a ``loader`` for one
directory listing or one leaf value at a time, only as the operator descends
into a node, and caches what it fetched so going back and forth never refetches.
This keeps remote traffic minimal: on a target, one keypress maps to at most one
request.

``TreeNavigator`` holds the navigation state and the per-path cache and has no
terminal dependency, so it can be unit-tested with a fake loader;
``browse_tree()`` wraps it in a prompt_toolkit ``Application``.

A ``loader`` is any object exposing:

* ``list(path) -> Iterable[(label, path, is_dir)]`` — a directory's children.
* ``read(path) -> str`` — a leaf's value.

Either call raises :class:`LoaderError` when the fetch fails; the message is
shown in place instead of the value.
"""

# Built-in imports
import json
from typing import Any, NamedTuple, Protocol

# Third party library imports
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

LIST_HINT = " ↑/↓ j/k move · Enter/→ open (fetches) · ←/Backspace up · q/Esc quit"
VALUE_HINT = " ↑/↓ j/k scroll · PgUp/PgDn page · ←/Backspace/Esc back · q quit"

STYLE = Style.from_dict(
    {
        "header": "bold reverse",
        "footer": "reverse",
        "selected": "reverse bold",
        "directory": "ansicyan",
        "empty": "italic ansibrightblack",
        "error": "ansired",
    }
)


class LoaderError(Exception):
    """A directory listing or leaf value could not be fetched."""


class Entry(NamedTuple):
    """A single node in the navigation tree."""

    label: str
    path: str
    is_dir: bool


class Loader(Protocol):
    """Protocol for fetching directory listings and leaf values."""

    def list(self, path: str) -> "list[tuple[str, str, bool]]":
        """Return the children of the directory at path."""
        ...

    def read(self, path: str) -> str:
        """Return the leaf value at path."""
        ...


def value_text(value: Any) -> str:
    """Render a leaf for display."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, int, float, bool)) or value is None:
        return json.dumps(value, indent=2)
    return str(value)


def follow(index: int, top: int, height: int) -> int:
    """Return the first visible row so that ``index`` stays on screen."""
    height = max(height, 1)
    if index < top:
        return index
    if index >= top + height:
        return index - height + 1
    return top


class TreeNavigator:
    """On-demand navigation state over a ``loader``.

    ``root_entries`` seeds the root listing so the first screen needs no extra
    fetch (the caller has usually just listed the root to decide whether to
    browse at all). Everything below the root is fetched lazily on ``enter()``.
    """

    def __init__(
        self,
        root_path: str,
        loader: Loader,
        root_entries: "list[tuple[str, str, bool]] | None" = None,
    ):
        self._loader = loader
        self._root = root_path
        self._listings: dict[str, list[Entry]] = {}
        self._values: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        if root_entries is not None:
            self._listings[root_path] = [Entry(*entry) for entry in root_entries]
        self._stack: list[str] = [root_path]
        self._saved: dict[str, int] = {}
        self.index = 0
        # ``(path, text, is_error)`` while a leaf (or a failed listing) is open.
        self.viewing: tuple[str, str, bool] | None = None

    @staticmethod
    def label(entry: Entry) -> str:
        """Return the display label, appending a slash for directories."""
        return f"{entry.label}/" if entry.is_dir else entry.label

    @property
    def current_dir(self) -> str:
        """Return the path of the directory currently being listed."""
        return self._stack[-1]

    @property
    def children(self) -> list[Entry]:
        """Return the cached child entries of the current directory."""
        return self._listings.get(self.current_dir, [])

    @property
    def selected(self) -> Entry | None:
        """Return the currently highlighted entry, or None if the listing is empty."""
        children = self.children
        return children[self.index] if children else None

    @property
    def path(self) -> str:
        """The path shown in the header: the open leaf, else the current dir."""
        return self.viewing[0] if self.viewing is not None else self.current_dir

    def _ensure_listing(self, path: str) -> None:
        if path in self._listings or path in self._errors:
            return
        try:
            self._listings[path] = [Entry(*entry) for entry in self._loader.list(path)]
        except LoaderError as exc:
            self._errors[path] = str(exc)

    def _ensure_value(self, path: str) -> None:
        if path in self._values or path in self._errors:
            return
        try:
            self._values[path] = self._loader.read(path)
        except LoaderError as exc:
            self._errors[path] = str(exc)

    def move(self, delta: int) -> None:
        """Move the selection cursor by delta rows within the current listing."""
        if self.viewing is None and self.children:
            self.index = max(0, min(len(self.children) - 1, self.index + delta))

    def enter(self) -> str | None:
        """Open the selected node, fetching it on first visit.

        Returns the text to display when a leaf (or a fetch error) is opened,
        or ``None`` when a directory was entered (the list view just changed).
        """
        if self.viewing is not None or (entry := self.selected) is None:
            return None
        if entry.is_dir:
            self._ensure_listing(entry.path)
            if entry.path in self._errors:
                self.viewing = (entry.path, self._errors[entry.path], True)
                return self.viewing[1]
            self._saved[self.current_dir] = self.index
            self._stack.append(entry.path)
            self.index = self._saved.get(entry.path, 0)
            return None
        self._ensure_value(entry.path)
        if entry.path in self._values:
            self.viewing = (entry.path, self._values[entry.path], False)
        else:
            self.viewing = (entry.path, self._errors[entry.path], True)
        return self.viewing[1]

    def back(self) -> bool:
        """Close the open leaf or go up one directory; False at the root."""
        if self.viewing is not None:
            self.viewing = None
            return True
        if len(self._stack) == 1:
            return False
        self._stack.pop()
        self.index = self._saved.get(self.current_dir, 0)
        return True


def browse_tree(
    root_path: str,
    loader: Loader,
    root_entries: "list[tuple[str, str, bool]] | None" = None,
    title: str = "",
    *,
    input=None,
    output=None,
) -> TreeNavigator:
    """Navigate ``loader``'s tree below ``root_path`` until the operator quits.

    Each descent fetches one node through ``loader``; nothing is prefetched.
    ``input``/``output`` are passed to prompt_toolkit (tests use pipe input).
    Must be called while no other prompt_toolkit application is running, and
    with host logging suppressed so a loader's own output cannot corrupt the
    screen. Returns the final navigator state.
    """
    navigator = TreeNavigator(root_path, loader, root_entries)
    view = {"scroll": 0, "top": 0, "lines": []}

    def body_height() -> int:
        return max(get_app().output.get_size().rows - 2, 1)

    def wrapped(text: str) -> list[str]:
        width = max(get_app().output.get_size().columns, 1)
        lines = []
        for line in text.splitlines() or [""]:
            line = line.expandtabs()
            lines.extend(line[i : i + width] for i in range(0, len(line), width) or [0])
        return lines or [""]

    def open_value(text: str) -> None:
        view["lines"], view["scroll"] = wrapped(text), 0

    def header() -> StyleAndTextTuples:
        suffix = "/" if navigator.viewing is None else ""
        return [("class:header", f" {title}{navigator.path}{suffix} ")]

    def footer() -> StyleAndTextTuples:
        hint = VALUE_HINT if navigator.viewing is not None else LIST_HINT
        if navigator.viewing is None and navigator.children:
            hint += f" · {navigator.index + 1}/{len(navigator.children)}"
        return [("class:footer", hint)]

    def body() -> StyleAndTextTuples:
        height = body_height()
        if navigator.viewing is not None:
            style = "class:error" if navigator.viewing[2] else ""
            lines = view["lines"]
            view["scroll"] = max(0, min(view["scroll"], len(lines) - height))
            return [(style, "\n".join(lines[view["scroll"] : view["scroll"] + height]))]
        children = navigator.children
        if not children:
            return [("class:empty", "  (empty)")]
        view["top"] = follow(navigator.index, view["top"], height)
        fragments: StyleAndTextTuples = []
        for row in range(view["top"], min(len(children), view["top"] + height)):
            entry = children[row]
            label = TreeNavigator.label(entry)
            if row == navigator.index:
                fragments.append(("class:selected", f"> {label}"))
            else:
                fragments.append(("class:directory" if entry.is_dir else "", f"  {label}"))
            fragments.append(("", "\n"))
        return fragments[:-1]

    bindings = KeyBindings()

    def scroll(delta: int) -> None:
        if navigator.viewing is not None:
            view["scroll"] = max(0, view["scroll"] + delta)
        else:
            navigator.move(delta)

    @bindings.add("up")
    @bindings.add("k")
    def _(event):
        scroll(-1)

    @bindings.add("down")
    @bindings.add("j")
    def _(event):
        scroll(1)

    @bindings.add("pageup")
    def _(event):
        scroll(-body_height())

    @bindings.add("pagedown")
    def _(event):
        scroll(body_height())

    @bindings.add("home")
    @bindings.add("g")
    def _(event):
        scroll(-(10**9))

    @bindings.add("end")
    @bindings.add("G")
    def _(event):
        scroll(10**9)

    @bindings.add("enter")
    @bindings.add("right")
    @bindings.add("l")
    def _(event):
        text = navigator.enter()
        if text is not None:
            open_value(text)

    @bindings.add("left")
    @bindings.add("backspace")
    @bindings.add("h")
    def _(event):
        navigator.back()

    @bindings.add("escape", eager=True)
    def _(event):
        if navigator.viewing is not None:
            navigator.back()
        else:
            event.app.exit()

    @bindings.add("q")
    @bindings.add("c-c")
    def _(event):
        event.app.exit()

    layout = Layout(
        HSplit(
            [
                Window(FormattedTextControl(header), height=1),
                Window(FormattedTextControl(body, focusable=True, show_cursor=False)),
                Window(FormattedTextControl(footer), height=1),
            ]
        )
    )
    Application(
        layout=layout,
        key_bindings=bindings,
        style=STYLE,
        full_screen=True,
        input=input,
        output=output,
    ).run()
    return navigator
