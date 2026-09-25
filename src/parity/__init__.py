"""Parity: AI accessibility auditor that finds and fixes WCAG issues."""

__version__ = "0.1.0"


def main() -> None:
    from parity.cli import main as cli_main

    cli_main()
