# Repository instructions

## Project

Toboggan turns an existing remote command execution primitive into a semi-interactive post-exploitation terminal. It does not discover or establish the initial RCE.

Read [`DEVELOPMENT.md`](DEVELOPMENT.md) when changing execution, OS detection, target command discovery, command transformations, actions, FIFO behavior, or local and remote artifacts. For focused changes, read only the relevant section and its linked source files.

When preparing a commit, first pull the current branch from its configured upstream with `git pull --rebase --autostash`; never commit against stale remote history. Then follow the human contribution and commit conventions in [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Core contracts

- A user execution module exposes `execute(command, timeout)` and returns clean command output as text.
- Keep transport-specific behavior in execution modules or handlers; keep target-side execution behavior in the executor, helpers, and actions.
- Put platform-dependent operations in OS-specific helpers or `linux.py`/`windows.py` action modules.
- Preserve Linux command-discovery fallback order and caching unless intentionally redesigning it.
- User actions override built-in actions with the same name.
- Custom execution modules and actions are trusted local Python code, not sandboxed extensions.
- Document any new local or remote artifacts and their cleanup behavior.
- Treat target cleanup as best-effort and keep cleanup possible when an operation fails partway through.

## Verification

Run the affected tests, or the full suite with:

```shell
uv run pytest -v
```
