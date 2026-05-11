# tests/test_action.py

import pytest
from toboggan.core.action import ActionsManager


class TestActionsManagerValidation:
    def test_invalid_os_raises(self):
        with pytest.raises(ValueError, match="Must be 'linux' or 'windows'"):
            ActionsManager(target_os="macos")

    def test_linux_os_accepted(self):
        manager = ActionsManager(target_os="linux")
        actions = manager.get_actions()
        assert isinstance(actions, dict)

    def test_windows_os_accepted(self):
        manager = ActionsManager(target_os="windows")
        actions = manager.get_actions()
        assert isinstance(actions, dict)

    def test_linux_actions_discovered(self):
        manager = ActionsManager(target_os="linux")
        actions = manager.get_actions()
        # Should find at least some built-in actions
        assert len(actions) > 0
        # Verify known actions exist
        expected = {"download", "upload", "fifo", "netcheck", "ip", "users"}
        found = set(actions.keys())
        assert expected.issubset(found), f"Missing actions: {expected - found}"

    def test_hide_unhide_excluded(self):
        manager = ActionsManager(target_os="linux")
        actions = manager.get_actions()
        assert "hide" not in actions
        assert "unhide" not in actions

    def test_actions_have_path(self):
        manager = ActionsManager(target_os="linux")
        actions = manager.get_actions()
        for name, info in actions.items():
            assert "path" in info, f"Action '{name}' missing 'path'"

    def test_get_action_returns_class(self):
        manager = ActionsManager(target_os="linux")
        action_cls = manager.get_action("download")
        assert action_cls is not None

    def test_get_action_nonexistent_returns_none(self):
        manager = ActionsManager(target_os="linux")
        action_cls = manager.get_action("nonexistent_action_xyz")
        assert action_cls is None
