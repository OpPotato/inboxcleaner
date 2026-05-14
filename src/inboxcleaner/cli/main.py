import click

from inboxcleaner.core.config import Paths
from inboxcleaner.core.logging_setup import configure_logging


@click.group()
@click.version_option("0.1.0", prog_name="inboxcleaner")
def cli() -> None:
    """Local-first Gmail cleanup tool."""
    configure_logging(Paths.default())


@cli.command()
def login() -> None:
    """Run the Gmail OAuth flow."""
    click.echo("login: not yet implemented (Task 14)")


@cli.command()
def sync() -> None:
    """Sync mail metadata into the local cache."""
    click.echo("sync: not yet implemented (Task 15)")


@cli.command()
def senders() -> None:
    """Print a table of sender groups."""
    click.echo("senders: not yet implemented (Task 16)")


@cli.command()
def regroup() -> None:
    """Re-run grouping over all senders."""
    click.echo("regroup: not yet implemented (Task 17)")


def main() -> None:
    cli()
