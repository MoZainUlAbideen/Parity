from typer.testing import CliRunner

from parity.cli import app

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "scan" in result.output and "baseline-eval" in result.output


def test_scan_refuses_internal_address_with_clear_message():
    result = runner.invoke(app, ["scan", "http://169.254.169.254/latest/meta-data"])
    assert result.exit_code == 2
    assert "Refused" in result.output
