"""Rich-powered interactive CLI for contact review and merge."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text
from rich.columns import Columns

from .vcards import load_all, Contact
from .matcher import find_duplicates, DuplicateCluster
from .merger import merge_cluster
from .exporter import export_vcf

console = Console()


def _show_stats(contacts: list[Contact], file_paths: list[str]):
    table = Table(title="Loaded Contacts", show_header=True, header_style="bold cyan")
    table.add_column("Source", style="dim")
    table.add_column("Contacts", justify="right", style="green")
    table.add_column("With Phone", justify="right")
    table.add_column("With Email", justify="right")

    by_file: dict[str, list[Contact]] = {}
    for c in contacts:
        by_file.setdefault(c.source_file, []).append(c)

    for fname, group in by_file.items():
        phones = sum(1 for c in group if c.phones)
        emails = sum(1 for c in group if c.emails)
        table.add_row(fname, str(len(group)), str(phones), str(emails))

    table.add_section()
    phones = sum(1 for c in contacts if c.phones)
    emails = sum(1 for c in contacts if c.emails)
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{len(contacts)}[/bold]", str(phones), str(emails))
    console.print(table)
    console.print()


def _show_cluster(cluster: DuplicateCluster, index: int, total: int):
    conf = cluster.confidence
    if conf >= 0.95:
        conf_style = "bold green"
        conf_label = "HIGH"
    elif conf >= 0.80:
        conf_style = "yellow"
        conf_label = "MEDIUM"
    else:
        conf_style = "red"
        conf_label = "LOW"

    header = Text()
    header.append(f"Cluster {index}/{total}  ", style="bold")
    header.append(f"[{conf_label} confidence: {conf:.0%}]", style=conf_style)

    console.print(Panel(header, border_style="blue", expand=False))
    console.print()

    for i, contact in enumerate(cluster.contacts):
        lines = []
        lines.append(f"  [bold cyan]Name:[/bold cyan]     {contact.full_name or '(no name)'}")
        if contact.org:
            lines.append(f"  [bold cyan]Org:[/bold cyan]      {contact.org}")
        if contact.title:
            lines.append(f"  [bold cyan]Title:[/bold cyan]    {contact.title}")
        phones = ", ".join(f"{p.number} ({p.type})" for p in contact.phones) or "(none)"
        lines.append(f"  [bold cyan]Phones:[/bold cyan]   {phones}")
        emails = ", ".join(e.address for e in contact.emails) or "(none)"
        lines.append(f"  [bold cyan]Emails:[/bold cyan]  {emails}")
        if contact.note:
            note = contact.note[:80] + ("..." if len(contact.note) > 80 else "")
            lines.append(f"  [bold cyan]Note:[/bold cyan]    {note}")
        lines.append(f"  [dim]Source: {contact.source_file}[/dim]")

        panel_text = "\n".join(lines)
        console.print(Panel(panel_text, title=f"Entry {i+1}", border_style="dim", expand=True))

    console.print()
    if cluster.signals:
        console.print("  [dim]Match signals:[/dim]")
        for sig in cluster.signals:
            console.print(f"    - {sig.kind}: {sig.detail}")
    console.print()


def _prompt_action(cluster: DuplicateCluster, auto_threshold: float) -> str:
    if cluster.confidence >= auto_threshold:
        return "merge"

    console.print("  [bold]Actions:[/bold]")
    console.print("    [green]y[/green] = Merge (accept suggested name)")
    console.print("    [yellow]n[/yellow] = Skip (keep separate)")
    console.print("    [cyan]r[/cyan] = Rename (choose the name)")
    console.print("    [red]k[/red] = Keep separate (mark as not duplicates)")
    console.print()

    while True:
        choice = Prompt.ask("  Your choice", choices=["y", "n", "r", "k"], default="y")
        if choice in ("y", "n", "r", "k"):
            return {"y": "merge", "n": "skip", "r": "rename", "k": "keep"}[choice]


def _get_custom_name(cluster: DuplicateCluster) -> str:
    console.print()
    console.print("  [dim]Current names:[/dim]")
    for c in cluster.contacts:
        console.print(f"    - {c.full_name or '(no name)'}")
    return Prompt.ask("  Enter the correct name")


def run_cli(file_paths: list[str], output: str, auto: bool, threshold: float, dry_run: bool, verbose: bool):
    paths = [Path(p) for p in file_paths]
    for p in paths:
        if not p.exists():
            console.print(f"[red]File not found: {p}[/red]")
            raise SystemExit(1)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Loading contacts...", total=None)
        contacts = load_all(paths)
        progress.update(task, description=f"Loaded {len(contacts)} contacts")

    _show_stats(contacts, file_paths)

    if len(contacts) < 2:
        console.print("[yellow]Need at least 2 contacts to find duplicates.[/yellow]")
        return

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Finding duplicates...", total=None)
        clusters = find_duplicates(contacts)
        progress.update(task, description=f"Found {len(clusters)} potential duplicate clusters")

    if not clusters:
        console.print("[green]No duplicates found. Your contacts are already clean![/green]")
        if not dry_run:
            export_vcf(contacts, output)
            console.print(f"[green]Exported {len(contacts)} contacts to {output}[/green]")
        return

    total_people = sum(len(c.contacts) for c in clusters)
    console.print(f"[bold]Found {len(clusters)} clusters ({total_people} contacts involved)[/bold]")
    console.print()

    if auto:
        auto_count = sum(1 for c in clusters if c.confidence >= threshold)
        console.print(f"[dim]Auto mode: {auto_count}/{len(clusters)} clusters above {threshold:.0%} threshold will be auto-merged[/dim]")
        console.print()

    merged_contacts: list[Contact] = []
    skipped: list[Contact] = []
    auto_merged = 0
    user_merged = 0
    kept_separate = 0

    for i, cluster in enumerate(clusters, 1):
        _show_cluster(cluster, i, len(clusters))

        if auto and cluster.confidence >= threshold:
            action = "merge"
            console.print(f"  [green]Auto-merging (confidence {cluster.confidence:.0%} >= {threshold:.0%})[/green]")
        else:
            action = _prompt_action(cluster, threshold if auto else 1.0)

        if action == "merge":
            merged = merge_cluster(cluster)
            merged_contacts.append(merged)
            auto_merged += 1 if (auto and cluster.confidence >= threshold) else 0
            user_merged += 0 if (auto and cluster.confidence >= threshold) else 1
            console.print(f"  [green]Merged as: {merged.full_name}[/green]")
        elif action == "rename":
            custom_name = _get_custom_name(cluster)
            merged = merge_cluster(cluster, chosen_name=custom_name)
            merged_contacts.append(merged)
            user_merged += 1
            console.print(f"  [green]Merged as: {merged.full_name}[/green]")
        elif action == "keep":
            kept_separate += len(cluster.contacts)
            for c in cluster.contacts:
                skipped.append(c)
            console.print("  [yellow]Keeping separate[/yellow]")
        else:
            console.print("  [dim]Skipped[/dim]")

        console.print()

    already_clean = [c for c in contacts if not any(c in cl.contacts for cl in clusters)]
    all_output = already_clean + merged_contacts + skipped
    unique_uids = set()
    deduped = []
    for c in all_output:
        uid = c.uid or c.full_name
        if uid not in unique_uids:
            unique_uids.add(uid)
            deduped.append(c)

    console.print()
    console.print(Panel("[bold]Summary[/bold]", border_style="green"))
    console.print(f"  Input contacts:       {len(contacts)}")
    console.print(f"  Duplicate clusters:   {len(clusters)}")
    console.print(f"  Auto-merged:          {auto_merged}")
    console.print(f"  User-merged:          {user_merged}")
    console.print(f"  Kept separate:        {kept_separate}")
    console.print(f"  Already clean:        {len(already_clean)}")
    console.print(f"  [bold]Output contacts:      {len(deduped)}[/bold]")
    console.print(f"  Saved:                {len(contacts) - len(deduped)} duplicates removed")
    console.print()

    if dry_run:
        console.print("[yellow]Dry run — no file written.[/yellow]")
        return

    count = export_vcf(deduped, output)
    console.print(f"[green]Exported {count} contacts to {output}[/green]")
    console.print()
    console.print("[dim]Import this .vcf file into your Samsung Contacts app or Google Contacts.[/dim]")
