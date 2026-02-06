# Bash commands
- source .venv/bin/activate: Activate the virtual environment 
- .venv/bin/python: Location of the Python interpreter
- uv add <package>: Add a package to the project
- uv remove <package>: Remove a package from the project
- uv run ruff check: Run the linter
- uv run ruff format: Run the auto-formatter
- uvx ty check: Run the type checker

# Code style
- Use ruff for linting and formatting
- Use uv to manage dependencies
- Follow PEP 8 style guidelines

# Workflow
- This project uses uv for project, dependency, and environment management
- Be sure to typecheck when you’re done making a series of code changes
- Run the linter and auto-formatter before committing code

# Starting the Django development server
2. Run the server: `python manage.py runserver 8001`
3. Access the application at `http://localhost:8001/`
