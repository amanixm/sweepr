"""Typer command-line interface for sweepr."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from sweepr import __version__
from sweepr.core import (
    InvalidPathError,
    MoveOperation,
    OrganizeMode,
    SkippedEntry,
    SweepPlan,
    SweeprError,
    SweepResult,
    UndoManifestNotFoundError,
    UndoResult,
    create_plan,
    execute_plan,
    format_size,
)
from sweepr.core import (
    undo as undo_sweep,
)

console = Console()

APP_HELP = """
[bold cyan]sweepr[/bold cyan] organizes files safely from the terminal.

[bold]Examples[/bold]
  sweepr organize ~/Downloads --by-type --dry-run
  sweepr organize ~/Downloads --by-type --recursive --apply
  sweepr organize ~/Downloads --by-date --dry-run
  sweepr undo ~/Downloads
"""

app = typer.Typer(
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=APP_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def version_callback(value: bool) -> None:
    """Print the package version for the global --version option."""

    if value:
        console.print(f"[bold cyan]sweepr[/bold cyan] {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=version_callback,
            help="Show the installed sweepr version and exit.",
            is_eager=True,
            rich_help_panel="Global Options",
        ),
    ] = False,
) -> None:
    """Run sweepr."""

    del version


@app.command(help="Organize a directory by file type or modification date.")
def organize(
    path: Annotated[
        Path,
        typer.Argument(
            help="Directory to organize.",
            show_default=False,
        ),
    ],
    by_type: Annotated[
        bool,
        typer.Option(
            "--by-type",
            help="Organize into folders such as Images, Documents, Videos, and Archives.",
            rich_help_panel="Mode",
        ),
    ] = False,
    by_date: Annotated[
        bool,
        typer.Option(
            "--by-date",
            help="Organize into YYYY/MM folders using each file's modification time.",
            rich_help_panel="Mode",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--apply",
            help="Preview changes without moving files. Use --apply to move files.",
            rich_help_panel="Safety",
        ),
    ] = True,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="Include files in nested directories.",
            rich_help_panel="Scan",
        ),
    ] = False,
    exclude: Annotated[
        str | None,
        typer.Option(
            "--exclude",
            help="Comma-separated glob patterns or paths to skip, such as node_modules,*.tmp.",
            rich_help_panel="Scan",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show skipped files and detailed errors.",
            rich_help_panel="Output",
        ),
    ] = False,
) -> None:
    """Plan and optionally apply a file organization sweep."""

    mode = _resolve_mode(by_type=by_type, by_date=by_date)

    try:
        with console.status("[bold cyan]Scanning files...[/bold cyan]", spinner="dots"):
            plan = create_plan(path, mode=mode, recursive=recursive, exclude=exclude)
    except SweeprError as exc:
        _print_error("Unable to create organization plan", str(exc))
        raise typer.Exit(code=1) from exc

    _print_plan(plan)

    if verbose:
        _print_skipped(plan.skipped)

    if dry_run:
        result = execute_plan(plan, dry_run=True)
        console.print(
            Panel.fit(
                "Dry run only. No files were moved.\n"
                "Run again with [bold]--apply[/bold] to execute.",
                border_style="yellow",
                title="Preview",
            )
        )
    else:
        result = _execute_with_progress(plan)

    _print_summary(plan, result)

    if result.errors:
        _print_errors(result.errors, verbose=verbose)
        raise typer.Exit(code=1)


@app.command(help="Restore files from the latest sweepr undo manifest.")
def undo(
    path: Annotated[
        Path,
        typer.Argument(
            help="Directory whose latest sweep should be undone.",
            show_default=False,
        ),
    ],
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed restore errors.",
            rich_help_panel="Output",
        ),
    ] = False,
) -> None:
    """Undo the latest applied sweep for a directory."""

    try:
        with console.status("[bold cyan]Restoring files...[/bold cyan]", spinner="dots"):
            result = undo_sweep(path)
    except UndoManifestNotFoundError as exc:
        _print_error("Nothing to undo", str(exc))
        raise typer.Exit(code=1) from exc
    except (InvalidPathError, SweeprError) as exc:
        _print_error("Unable to undo sweep", str(exc))
        raise typer.Exit(code=1) from exc

    _print_undo_summary(result)

    if result.errors:
        _print_errors(result.errors, verbose=verbose)
        raise typer.Exit(code=1)


def _resolve_mode(*, by_type: bool, by_date: bool) -> OrganizeMode:
    if by_type == by_date:
        _print_error("Choose one mode", "Use exactly one of --by-type or --by-date.")
        raise typer.Exit(code=2)
    return OrganizeMode.TYPE if by_type else OrganizeMode.DATE


def _execute_with_progress(plan: SweepPlan) -> SweepResult:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        task_id = progress.add_task("Moving files", total=len(plan.operations))

        def advance(
            _operation: MoveOperation,
            _destination: Path | None,
            _error: str | None,
        ) -> None:
            progress.advance(task_id)

        return execute_plan(plan, dry_run=False, on_operation=advance)


def _print_plan(plan: SweepPlan) -> None:
    if not plan.operations:
        console.print(
            Panel.fit(
                "No files need to be moved.",
                title="Plan",
                border_style="green",
            )
        )
        return

    table = Table(
        title=f"Planned moves ({len(plan.operations)})",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
    )
    table.add_column("Source", overflow="fold")
    table.add_column("Destination", overflow="fold")
    table.add_column("Category", style="cyan")
    table.add_column("Size", justify="right")

    preview_limit = 25
    for operation in plan.operations[:preview_limit]:
        table.add_row(
            _display_path(operation.source),
            _display_path(operation.destination),
            operation.category,
            format_size(operation.size),
        )

    remaining = len(plan.operations) - preview_limit
    if remaining > 0:
        table.add_row(
            f"... {remaining} more",
            "",
            "",
            "",
            style="dim",
        )

    console.print(table)


def _print_skipped(skipped: tuple[SkippedEntry, ...]) -> None:
    if not skipped:
        return

    table = Table(title="Skipped files", box=box.SIMPLE)
    table.add_column("Path", overflow="fold")
    table.add_column("Reason", overflow="fold")

    for entry in skipped:
        table.add_row(_display_path(entry.path), entry.reason)

    console.print(table)


def _print_summary(plan: SweepPlan, result: SweepResult) -> None:
    table = Table(title="Summary", box=box.ROUNDED)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Root", _display_path(result.root))
    table.add_row("Mode", plan.mode.value)
    table.add_row("Recursive", "yes" if plan.recursive else "no")
    table.add_row("Dry run", "yes" if result.dry_run else "no")
    table.add_row("Planned", str(result.planned))
    table.add_row("Moved", str(result.moved))
    table.add_row("Skipped", str(result.skipped))
    table.add_row("Bytes planned", format_size(plan.total_size))
    table.add_row("Errors", str(len(result.errors)))

    if result.manifest_path is not None:
        table.add_row("Undo manifest", _display_path(result.manifest_path))

    console.print(table)


def _print_undo_summary(result: UndoResult) -> None:
    table = Table(title="Undo Summary", box=box.ROUNDED)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Root", _display_path(result.root))
    table.add_row("Restored", str(result.restored))
    table.add_row("Skipped", str(result.skipped))
    table.add_row("Manifest", _display_path(result.manifest_path))
    table.add_row("Errors", str(len(result.errors)))
    console.print(table)


def _print_errors(errors: tuple[str, ...], *, verbose: bool) -> None:
    if verbose:
        message = "\n".join(f"- {escape(error)}" for error in errors)
    else:
        message = f"{len(errors)} operation failed. Re-run with --verbose for details."
    _print_error("Some operations failed", message)


def _print_error(title: str, message: str) -> None:
    console.print(
        Panel.fit(
            escape(message),
            title=f"[red]{escape(title)}[/red]",
            border_style="red",
        )
    )


def _display_path(path: Path) -> str:
    try:
        return escape(str(path.relative_to(Path.cwd())))
    except ValueError:
        return escape(str(path))
