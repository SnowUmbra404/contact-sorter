"""Contact Sorter — merge and deduplicate Samsung VCF contact lists."""

import click
from src.tui import run_tui
from src.cli import run_cli


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("-o", "--output", default="merged_contacts.vcf", help="Output VCF file path")
@click.option("--auto", is_flag=True, help="CLI mode: auto-accept high-confidence merges")
@click.option("--merge-only", is_flag=True, help="CLI mode: merge all without review")
@click.option("--fix-case", is_flag=True, help="Title-case all names (RAJESH → Rajesh)")
@click.option("--clean-names", is_flag=True, help="Apply all name cleanup")
@click.option("--dry-run", is_flag=True, help="CLI mode: show what would happen without writing")
@click.option("--tui", "force_tui", is_flag=True, help="Force TUI mode even with other flags")
def main(files, output, auto, merge_only, fix_case, clean_names, dry_run, force_tui):
    """Merge and deduplicate VCF contact files.

    Pass one or more .vcf files exported from Samsung Contacts or Google Contacts.

    Interactive TUI (default):

        contact-sorter mine.vcf father.vcf

    CLI mode (with flags):

        contact-sorter mine.vcf father.vcf --auto

        contact-sorter mine.vcf father.vcf --merge-only --clean-names

        contact-sorter mine.vcf father.vcf --dry-run
    """
    cli_flags = any([auto, merge_only, fix_case, clean_names, dry_run, output != "merged_contacts.vcf"])

    if cli_flags and not force_tui:
        run_cli(
            file_paths=list(files),
            output=output,
            auto=auto,
            threshold=0.95,
            dry_run=dry_run,
            verbose=False,
            fix_case=fix_case,
            strip_honorifics=False,
            clean_names=clean_names,
            merge_only=merge_only,
        )
    else:
        run_tui(list(files))


if __name__ == "__main__":
    main()
