import click
from src.session import run_session


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("-o", "--output", default="out/merged_contacts.vcf", help="Output VCF file")
def main(files, output):
    """Organize and deduplicate VCF contact files interactively."""
    if not files:
        raise click.UsageError("Provide at least one .vcf file.")
    run_session(list(files), output)


if __name__ == "__main__":
    main()
