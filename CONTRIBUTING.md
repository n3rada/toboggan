# Contributing

Thank you for improving Toboggan. Keep changes focused, understandable, and compatible with the execution and cleanup contracts described in [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Workflow

1. Work on a focused branch.
2. Before committing, update it from its configured upstream with `git pull --rebase --autostash`.
3. Run the relevant tests, or the full suite with `uv run pytest -v`.
4. Submit a pull request that explains the behavior changed and how it was verified.

## Commit Conventions

- Submit one focused commit for a completed change. Amend it during iteration instead of adding fixup commits.
- Keep the subject short and on one line using the [Conventional Commits 1.0.0 specification](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): summary` or `type: summary`.
- Use `feat`, `fix`, `refactor`, `test`, `docs`, or `chore` as appropriate. Omit the scope rather than using empty parentheses.
- Commit with the human contributor's configured identity. Never add an AI or LLM as a co-author or include AI-generated attribution trailers.
- Sign the commit. The human contributor is responsible for understanding, reviewing, and owning every submitted change.
- Preserve another contributor's commits and authorship on shared pull requests unless a history rewrite is explicitly agreed.

Examples: `feat(fifo): support a custom shell`, `fix(kube-check): preserve API group restrictions`, `test(upload): cover interrupted transfers`, and `docs: explain command discovery`.

Avoid vague subjects such as `fix stuff`, empty scopes such as `feat(): add an action`, multi-line messages, and AI `Co-authored-by` trailers.
