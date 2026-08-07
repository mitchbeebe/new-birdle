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

# Agent Workflow
The user plans milestones and issues in the Birdle Linear project. From there, agents carry each issue through planning, implementation, and review.

- Orchestration: a managerial Claude Code session coordinates each issue through planner → implementer → reviewer → implementer, using the `herdr` skill to spawn and control each role. Spawn agents into a dedicated `agents` tab in the milestone's Herdr workspace (create it once per milestone if it doesn't exist) — never split panes inside the orchestrator's own tab.
- Worktree per milestone: create one git worktree per milestone, branched from a fresh `origin/main`, and name the worktree directory (and its Herdr workspace) for the milestone. All of that milestone's issue branches stack inside this worktree; there's no separate "milestone" git branch — the stack is rooted directly at `origin/main`.
- Stacked branches per issue: inside the milestone worktree, use the `gh-stack` skill (`gh stack init` for the first issue, `gh stack add` for each one after) to stack one branch per issue on top of the previous one. Name each branch the lowercase kebab-case Linear issue ID (e.g. `bir-142`) — never a paraphrased title. The branch's PR carries the same name.
- Planner: spawn a `herdr` agent named `<linear-id>-planner` in the milestone's `agents` tab. It reads the Linear issue, produces a concrete implementation plan (files, functions, sequencing, verification steps), and attaches/updates it on the Linear issue. The planner never writes code.
- Implementer: once the plan is ready, spawn `<linear-id>-implementer` in the same tab, hand it the approved plan, and have it create the issue's stacked branch (`gh stack add <linear-id>`) and implement it.
- Independent review: when the implementer believes the change is done, it spawns `<linear-id>-reviewer` as a fresh agent with no implementation history to review the diff against the plan and this file. The reviewer never writes code — it reports findings back to the implementer, who resolves them. Loop reviewer → implementer until the reviewer has no further findings.
- Verification gate before opening a PR: `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, and `python manage.py test` must all pass on the issue's branch.
- Opening the PR: once verification passes and the reviewer has signed off, the implementer runs `gh stack submit --auto` to push the branch and open its draft PR (base is the previous branch in the stack, or `origin/main` for the first issue in the milestone). The PR description links the Linear issue (`[LINEAR-ID](url)`).
- Human review: PRs are opened as drafts for the user to review — no agent merges a PR or marks a Linear issue Done. That stays an explicit user action.
- Close out the team: once an issue's PR is open, close that issue's `<linear-id>-planner`, `<linear-id>-implementer`, and `<linear-id>-reviewer` agents/panes before starting the next issue in the milestone. Don't leave finished roles running.
