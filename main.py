"""Contact Sorter — merge and deduplicate Samsung VCF contact lists."""

import click
from src.cli import run_cli


@click.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("-o", "--output", default="merged_contacts.vcf", help="Output VCF file path")
@click.option("--auto", is_flag=True, help="Auto-accept high-confidence merges")
@click.option("--threshold", default=0.95, type=float, help="Auto-accept confidence threshold (0-1)")
@click.option("--dry-run", is_flag=True, help="Show what would merge without writing")
@click.option("-v", "--verbose", is_flag=True, help="Show all matching details")
@click.option("--fix-case", is_flag=True, help="Title-case all names (RAJESH → Rajesh)")
@click.option("--strip-honorifics", is_flag=True, help="Remove Mr./Mrs./Dr./Smt./Shri/Ji from names")
@click.option("--clean-names", is_flag=True, help="Apply all name cleanup (case + honorifics + spacing)")
@click.option("--merge-only", is_flag=True, help="Skip review, merge all clusters automatically")
def main(files, output, auto, threshold, dry_run, verbose, fix_case, strip_honorifics, clean_names, merge_only):
    """Merge and deduplicate VCF contact files.

    Pass one or more .vcf files exported from Samsung Contacts or Google Contacts.

    Examples:

        contact-sorter mine.vcf father.vcf

        contact-sorter mine.vcf father.vcf --auto --threshold 0.90

        contact-sorter mine.vcf father.vcf --clean-names --fix-case

        contact-sorter mine.vcf father.vcf --merge-only
    """
    run_cli(
        file_paths=list(files),
        output=output,
        auto=auto,
        threshold=threshold,
        dry_run=dry_run,
        verbose=verbose,
        fix_case=fix_case,
        strip_honorifics=strip_honorifics,
        clean_names=clean_names,
        merge_only=merge_only,
    )
    """Merge and deduplicate VCF contact files.

    Pass one or more .vcf files exported from Samsung Contacts or Google Contacts.

    Examples:

        contact-sorter mine.vcf father.vcf

        contact-sorter mine.vcf father.vcf --auto --threshold 0.90

        contact-sorter mine.vcf father.vcf --dry-run
    """
    run_cli(
        file_paths=list(files),
        output=output,
        auto=auto,
        threshold=threshold,
        dry_run=dry_run,
        verbose=verbose,
    )


if __name__ == "__main__":
    main()
