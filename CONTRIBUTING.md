# Contributing

Contributions are welcome, and they are greatly appreciated! Every little bit helps, and credit will always be given.

You can contribute in many ways:

## Types of Contributions

### Report Bugs

Report bugs at https://github.com/Feverup/aiocop/issues.

If you are reporting a bug, please include:

- Your operating system name and version.
- Your Python version.
- Any details about your local setup that might be helpful in troubleshooting.
- Detailed steps to reproduce the bug.

### Fix Bugs

Look through the GitHub issues for bugs. Anything tagged with "bug" and "help wanted" is open to whoever wants to implement it.

### Implement Features

Look through the GitHub issues for features. Anything tagged with "enhancement" and "help wanted" is open to whoever wants to implement it.

### Write Documentation

aiocop could always use more documentation, whether as part of the official docs, in docstrings, or even on the web in blog posts, articles, and such.

### Submit Feedback

The best way to send feedback is to file an issue at https://github.com/Feverup/aiocop/issues.

If you are proposing a feature:

- Explain in detail how it would work.
- Keep the scope as narrow as possible, to make it easier to implement.
- Remember that this is a volunteer-driven project, and that contributions are welcome :)

## Get Started!

Ready to contribute? Here's how to set up `aiocop` for local development.

1. Fork the `aiocop` repo on GitHub.

2. Clone your fork locally:

   ```sh
   git clone git@github.com:your_name_here/aiocop.git
   cd aiocop
   ```

3. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

4. Install the project with development dependencies:

   ```sh
   uv sync --extra test
   ```

5. Create a branch for local development:

   ```sh
   git checkout -b name-of-your-bugfix-or-feature
   ```

   Now you can make your changes locally.

6. When you're done making changes, check that your changes pass linting and tests:

   ```sh
   # Run linter
   uv run ruff check

   # Run tests
   uv run pytest
   ```

7. Commit your changes and push your branch to GitHub:

   ```sh
   git add .
   git commit -m "Your detailed description of your changes."
   git push origin name-of-your-bugfix-or-feature
   ```

8. Submit a pull request through the GitHub website.

## Pull Request Guidelines

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests.
2. If the pull request adds functionality, the docs should be updated. Put your new functionality into a function with a docstring, and add the feature to the list in README.md.
3. The pull request should work for Python 3.10, 3.11, 3.12, and 3.13. Tests run in GitHub Actions on every pull request to the main branch, make sure that the tests pass for all supported Python versions.

## Tips

To run a subset of tests:

```sh
uv run pytest tests/test_aiocop.py -k "test_name"
```

To run tests with coverage:

```sh
uv run coverage run -m pytest
uv run coverage report
```

## Deploying

A reminder for the maintainers on how to deploy:

1. Make sure all your changes are committed (including an entry in HISTORY.md).

2. Update the version in `pyproject.toml`:

   ```toml
   version = "0.2.0"
   ```

3. Commit the version bump:

   ```sh
   git add pyproject.toml HISTORY.md
   git commit -m "Bump version to 0.2.0"
   git push
   ```

4. Create and push a tag:

   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```

The GitHub Actions workflow will automatically build and publish the package to PyPI when a new tag is pushed.

## Code of Conduct

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.
