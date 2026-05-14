# Contributing

Thanks for helping improve `sweepr`.

## Setup

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

## Checks

Run these before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest
```

## Pull requests

- Keep changes focused.
- Add or update tests for behavior changes.
- Prefer clear user-facing error messages.
- Do not add file-moving behavior without a dry-run-safe test.
