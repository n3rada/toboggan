from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from toboggan.core.utils.navigator import (
    LoaderError,
    TreeNavigator,
    browse_tree,
    follow,
    value_text,
)

# (label, path, is_dir) children per directory path.
LISTINGS = {
    "meta-data/": [
        ("ami-id", "meta-data/ami-id", False),
        ("iam", "meta-data/iam/", True),
        ("empty", "meta-data/empty/", True),
    ],
    "meta-data/iam/": [
        ("info", "meta-data/iam/info", False),
        ("security-credentials", "meta-data/iam/security-credentials/", True),
    ],
    "meta-data/iam/security-credentials/": [
        ("web", "meta-data/iam/security-credentials/web", False),
    ],
    "meta-data/empty/": [],
}
VALUES = {
    "meta-data/ami-id": "ami-123",
    "meta-data/iam/info": '{"Code": "Success"}',
    "meta-data/iam/security-credentials/web": "{}",
}
ROOT = "meta-data/"


class Loader:
    """Records every fetch so tests can assert laziness and caching."""

    def __init__(self):
        self.listed = []
        self.values = []

    def list(self, path):
        self.listed.append(path)
        if path not in LISTINGS:
            raise LoaderError(f"no listing for {path}")
        return LISTINGS[path]

    def read(self, path):
        self.values.append(path)
        if path not in VALUES:
            raise LoaderError(f"no value for {path}")
        return VALUES[path]


def make(loader=None):
    loader = loader or Loader()
    return TreeNavigator(ROOT, loader, LISTINGS[ROOT]), loader


def test_root_listing_needs_no_fetch():
    navigator, loader = make()
    labels = [TreeNavigator.label(entry) for entry in navigator.children]
    assert labels == ["ami-id", "iam/", "empty/"]
    assert navigator.path == "meta-data/"
    assert loader.listed == []  # root was seeded


def test_move_is_bounded():
    navigator, _ = make()
    navigator.move(-5)
    assert navigator.index == 0
    navigator.move(99)
    assert navigator.index == 2


def test_descend_fetches_only_the_opened_node():
    navigator, loader = make()
    navigator.move(1)  # iam/
    assert navigator.enter() is None
    assert loader.listed == ["meta-data/iam/"]  # only iam/, not ami-id or empty/
    assert navigator.current_dir == "meta-data/iam/"
    assert [e.label for e in navigator.children] == ["info", "security-credentials"]

    assert navigator.enter() == '{"Code": "Success"}'  # open the info leaf
    assert navigator.viewing[0] == "meta-data/iam/info"
    assert loader.values == ["meta-data/iam/info"]


def test_cache_prevents_refetch():
    navigator, loader = make()
    navigator.move(1)
    navigator.enter()  # list iam/
    navigator.enter()  # read iam/info
    navigator.back()  # close leaf
    navigator.back()  # up to root (selection restored to iam/)
    navigator.enter()  # iam/ again
    navigator.enter()  # iam/info again
    assert loader.listed == ["meta-data/iam/"]
    assert loader.values == ["meta-data/iam/info"]


def test_back_restores_selection():
    navigator, _ = make()
    navigator.move(1)
    navigator.enter()  # into iam/
    navigator.move(1)
    navigator.enter()  # into security-credentials/
    assert navigator.back()
    assert navigator.selected.label == "security-credentials"
    assert navigator.back()
    assert navigator.selected.label == "iam"
    assert navigator.back() is False


def test_empty_directory():
    navigator, loader = make()
    navigator.move(2)
    assert navigator.enter() is None  # into empty/
    assert navigator.children == [] and navigator.selected is None
    assert navigator.enter() is None
    assert loader.listed == ["meta-data/empty/"]


def test_failed_listing_is_shown_in_place():
    loader = Loader()
    navigator = TreeNavigator(ROOT, loader, [("broken", "meta-data/broken/", True)])
    text = navigator.enter()
    assert "no listing" in text
    assert navigator.viewing[2] is True  # error flag
    assert navigator.current_dir == "meta-data/"  # did not descend


def test_failed_leaf_is_shown_in_place():
    loader = Loader()
    navigator = TreeNavigator(ROOT, loader, [("x", "meta-data/x", False)])
    text = navigator.enter()
    assert "no value" in text
    assert navigator.viewing[2] is True


def test_value_text_and_follow():
    assert value_text("x") == "x"
    assert value_text([1, 2]) == "[\n  1,\n  2\n]"
    assert follow(index=0, top=3, height=5) == 0
    assert follow(index=9, top=0, height=5) == 5
    assert follow(index=4, top=2, height=5) == 2


def test_browse_tree_drives_keys_until_quit():
    loader = Loader()
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            pipe.send_text("j\r\rq")  # select iam/, open it, open info, quit
            navigator = browse_tree(
                ROOT, loader, LISTINGS[ROOT], title="test ",
                input=pipe, output=DummyOutput(),
            )

    assert navigator.path == "meta-data/iam/info"
    assert loader.listed == ["meta-data/iam/"]
    assert loader.values == ["meta-data/iam/info"]
