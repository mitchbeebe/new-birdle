See [README.md](README.md) for what this app does and its feature set.

# Code style
- Use ruff for linting and formatting
- Use uv to manage dependencies
- Follow PEP 8 style guidelines

# Engineering Philosophy
- Think before coding: state assumptions, surface tradeoffs and ambiguous interpretations, push back if a simpler approach exists, and stop to ask when genuinely confused rather than guessing silently.
- Simplicity first: write the minimum code that solves the problem — no speculative features, abstractions, or configurability beyond what was asked. If a senior engineer would call it overcomplicated, simplify.
- Surgical changes: touch only what the task requires. Don't refactor or reformat adjacent code, match existing style, and only remove dead code your change orphaned — mention other dead code instead of deleting it. Every changed line should trace to the request.
- Goal-driven execution: turn imperative tasks into verifiable goals (e.g. "fix the bug" → "write a failing test, then make it pass") and state a brief plan with a verification step for each stage of multi-step work.

# Workflow
- This project uses uv for project, dependency, and environment management
- Ruff and ty are enforced by pre-commit hooks — don't skip hooks to work around a failure; fix the underlying issue instead
- Be sure to typecheck when you're done making a series of code changes

# Starting the Django development server
- Run the server: `python manage.py runserver 8001`
- Access the application at `http://localhost:8001/`

