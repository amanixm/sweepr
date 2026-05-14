# sweepr

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/amanixm/sweepr/actions/workflows/ci.yml/badge.svg)](https://github.com/amanixm/sweepr/actions/workflows/ci.yml)
[![Install with pipx](https://img.shields.io/badge/install%20with-pipx-2f6f9f)](https://pipx.pypa.io/)
[![Typer + Rich](https://img.shields.io/badge/CLI-Typer%20%2B%20Rich-purple)](https://typer.tiangolo.com/)

`sweepr` is a smart file organizer for the terminal. It previews exactly what it
will move, then safely organizes a directory by file type or modification date,
with undo metadata for applied sweeps.

Dry-run is the default. Files are only moved when you pass `--apply`.

## Features

- Organize by type: `Images`, `Documents`, `Videos`, `Archives`, `Audio`, `Code`, and more.
- Organize by modification date into `YYYY/MM/`.
- Safe preview mode with Rich tables.
- Category summaries for dry-run previews.
- Recursive scanning for nested inbox folders.
- Undo support using `.sweepr` manifests.
- `sweepr types` command for supported file categories.
- Collision-safe destination names.
- Friendly errors, progress indicators, and summary reports.
- Modern `src/` package layout with Typer, Rich, pytest, Ruff, and GitHub Actions.

## Installation

Install directly from GitHub with `pipx`:

```bash
pipx install git+https://github.com/amanixm/sweepr.git
```

Or install from a local checkout:

```bash
git clone https://github.com/amanixm/sweepr.git
cd sweepr
pipx install .
```

For development:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Usage

Preview organizing a folder by file type. This is the safest first command:

```bash
sweepr organize ~/Downloads --by-type --dry-run
```

Apply the same type-based organization:

```bash
sweepr organize ~/Downloads --by-type --apply
```

Organize nested files recursively:

```bash
sweepr organize ~/Downloads --by-type --recursive --apply
```

Preview organizing by modification date:

```bash
sweepr organize ~/Downloads --by-date --dry-run
```

List supported file categories and extensions:

```bash
sweepr types
```

Undo the latest applied sweep:

```bash
sweepr undo ~/Downloads
```

Show version:

```bash
sweepr --version
```

Show help:

```bash
sweepr --help
sweepr organize --help
```

## Suggested GitHub topics

Use these topics on the repository to help developers find the project:

```text
python
cli
typer
rich
file-organizer
automation
productivity
open-source
```

## Safety model

`sweepr` is designed to avoid surprising file operations:

- `--dry-run` is the default.
- Applied runs create an undo manifest in `<path>/.sweepr/`.
- Existing destination files are never overwritten.
- Duplicate names get a numbered suffix, such as `photo (1).jpg`.
- Symlinks and internal `.sweepr` metadata are skipped.
- Undo will not overwrite a file that appeared at the original location after the sweep.

## Development

Run tests:

```bash
pytest
```

Run linting and formatting checks:

```bash
ruff check .
ruff format --check .
```

Format code:

```bash
ruff format .
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

MIT. See [LICENSE](LICENSE).
