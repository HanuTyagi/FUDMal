"""CLI entry-point stub (launches the GUI)."""

import contextlib
import sys


def main() -> None:
    """Launch the FUDMal builder GUI."""
    # Defer the import so the package can be imported/tested without Tkinter.
    try:
        import tkinter  # noqa: F401 – validate Tkinter is available early

        import main as _builder  # type: ignore[import-not-found]

        app = _builder.UnifiedBuilderApp()
        with contextlib.suppress(Exception):
            app.iconbitmap("FUDMal.ico")
        app.mainloop()
    except ImportError as exc:
        print(f"Cannot start GUI: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
