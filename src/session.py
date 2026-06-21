from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.rule import Rule

from .vcards import parse_vcf, Contact
from .grouper import group_by_name, group_by_phone
from .merger import merge_list
from .exporter import export_vcf
from .normalize import title_case_name

console = Console()


@dataclass
class MergeDecision:
    contacts: list[Contact]
    name: str


def _suggest_name(contacts: list[Contact]) -> str:
    names = [c.full_name.strip() for c in contacts if c.full_name.strip()]
    if not names:
        return ""
    return max(names, key=len)


def _show_group(group: list[Contact], idx: int, total: int, kind: str) -> None:
    console.print()
    console.rule(f"Group {idx} / {total}  [dim]({kind})[/dim]")
    table = Table(show_header=True, header_style="bold", show_lines=False, box=None, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", min_width=22)
    table.add_column("Phone", min_width=18)
    table.add_column("Type", width=6)
    table.add_column("Source", style="dim")

    for i, c in enumerate(group, 1):
        name = c.full_name or "(no name)"
        if c.phones:
            for j, p in enumerate(c.phones):
                table.add_row(
                    str(i) if j == 0 else "",
                    name if j == 0 else "",
                    p.number,
                    p.type,
                    c.source_file if j == 0 else "",
                )
        else:
            table.add_row(str(i), name, "(no phone)", "", c.source_file)

    console.print(table)



def _review_groups(groups: list[list[Contact]], kind: str) -> dict[int, MergeDecision]:
    decisions: dict[int, MergeDecision] = {}
    idx = 0

    while idx < len(groups):
        group = groups[idx]
        _show_group(group, idx + 1, len(groups), kind)
        suggested = _suggest_name(group)

        hint = (
            "  [bold]m[/bold]=merge  [bold]r[/bold]=rename  [bold]s[/bold]=subset  "
            "[bold]k[/bold]=keep  [bold]n[/bold]=skip  [bold]a[/bold]=accept all remaining"
        )
        if idx > 0:
            hint += "  [bold]b[/bold]=back"
        console.print(f"  Suggested: [bold]{suggested}[/bold]")
        console.print(hint)

        while True:
            raw = Prompt.ask("  Action", default="m").strip().lower()

            if raw == "b":
                if idx > 0:
                    idx -= 1
                    decisions.pop(idx, None)
                break

            if raw == "m":
                decisions[idx] = MergeDecision(group, suggested)
                idx += 1
                break

            elif raw == "r":
                name = Prompt.ask("  New name").strip()
                if name:
                    decisions[idx] = MergeDecision(group, name)
                    idx += 1
                    break

            elif raw == "s":
                raw_sel = Prompt.ask("  Numbers to merge (e.g. 1,3)").strip()
                try:
                    sel = [int(x.strip()) - 1 for x in raw_sel.split(",") if x.strip().isdigit()]
                    sel = [i for i in sel if 0 <= i < len(group)]
                    if len(sel) < 2:
                        console.print("[red]  Need at least 2.[/red]")
                        continue
                    subset = [group[i] for i in sel]
                    name = Prompt.ask("  Name", default=_suggest_name(subset)).strip()
                    decisions[idx] = MergeDecision(subset, name or _suggest_name(subset))
                    idx += 1
                    break
                except (ValueError, IndexError):
                    console.print("[red]  Invalid input.[/red]")

            elif raw in ("k", "n"):
                idx += 1
                break

            elif raw == "a":
                for j in range(idx, len(groups)):
                    decisions[j] = MergeDecision(groups[j], _suggest_name(groups[j]))
                idx = len(groups)
                break

            else:
                console.print("[red]  Unknown: m/r/s/k/n/a/b[/red]")

    return decisions


def _show_summary(groups: list[list[Contact]], decisions: dict[int, MergeDecision]) -> None:
    console.print()
    console.rule("Summary")

    merge_count = len(decisions)
    keep_count = len(groups) - merge_count
    contacts_in = sum(len(d.contacts) for d in decisions.values())

    console.print(
        f"  Merging [bold]{merge_count}[/bold] group(s) "
        f"({contacts_in} contacts → {merge_count})  |  "
        f"Keeping separate: [bold]{keep_count}[/bold] group(s)"
    )
    console.print()

    if decisions:
        table = Table(show_header=True, header_style="bold", show_lines=True, padding=(0, 1))
        table.add_column("Will be merged", min_width=40)
        table.add_column("Result name", min_width=22)
        for d in decisions.values():
            before = "\n".join(c.full_name or "(no name)" for c in d.contacts)
            table.add_row(before, f"→ {d.name}")
        console.print(table)
        console.print()


def _apply_merges(
    contacts: list[Contact],
    groups: list[list[Contact]],
    decisions: dict[int, MergeDecision],
) -> list[Contact]:
    merged_ids: set[int] = set()
    merged_results: list[Contact] = []

    for d in decisions.values():
        for c in d.contacts:
            merged_ids.add(id(c))
        merged_results.append(merge_list(d.contacts, d.name))

    remaining = [c for c in contacts if id(c) not in merged_ids]
    return remaining + merged_results


def _find_keywords(contacts: list[Contact]) -> list[tuple[str, list[Contact]]]:
    word_contacts: dict[str, list[Contact]] = {}
    for c in contacts:
        if not c.full_name:
            continue
        words = set(re.sub(r"[^a-z0-9]", " ", c.full_name.lower()).split())
        for w in words:
            if len(w) >= 3:
                word_contacts.setdefault(w, []).append(c)
    result = [(w, cs) for w, cs in word_contacts.items() if len(cs) >= 2]
    result.sort(key=lambda x: -len(x[1]))
    return result


def _apply_keyword_change(
    contacts: list[Contact], keyword: str, position: str, casing: str
) -> int:
    pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)

    kw_display = keyword
    if casing == "u":
        kw_display = keyword.upper()
    elif casing == "l":
        kw_display = keyword.lower()
    elif casing == "t":
        kw_display = keyword.title()

    count = 0
    for c in contacts:
        if not c.full_name or not pattern.search(c.full_name):
            continue
        name_without = pattern.sub("", c.full_name)
        name_without = re.sub(r"\s+", " ", name_without).strip()

        if position == "r":
            c.full_name = name_without
        elif position == "k":
            c.full_name = pattern.sub(kw_display, c.full_name)
        elif position == "s":
            c.full_name = f"{kw_display} {name_without}".strip()
        elif position == "e":
            c.full_name = f"{name_without} {kw_display}".strip()

        c.full_name = re.sub(r"\s+", " ", c.full_name).strip()
        count += 1
    return count


def _keyword_phase(contacts: list[Contact]) -> None:
    keywords = _find_keywords(contacts)
    if not keywords:
        return

    console.print()
    console.rule("[bold]Phase 3 / 3 — Keyword Rename[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, box=None, padding=(0, 1))
    table.add_column("#", width=4, style="dim")
    table.add_column("Keyword", min_width=14)
    table.add_column("Count", width=7)
    table.add_column("Sample contacts")

    for i, (word, cs) in enumerate(keywords, 1):
        samples = ", ".join(c.full_name for c in cs[:3])
        if len(cs) > 3:
            samples += f" +{len(cs) - 3} more"
        table.add_row(str(i), word, str(len(cs)), samples)

    console.print(table)
    console.print()

    while True:
        raw = Prompt.ask("Keyword # to organize, or [d]one").strip().lower()
        if raw in ("d", "done", ""):
            break

        try:
            ki = int(raw) - 1
            if ki < 0 or ki >= len(keywords):
                console.print("[red]Invalid number.[/red]")
                continue
            keyword, kw_contacts = keywords[ki]
        except ValueError:
            console.print("[red]Enter a number or 'd'.[/red]")
            continue

        console.print()
        console.print(f"  Keyword: [bold]{keyword}[/bold]  ({len(kw_contacts)} contacts)")
        for c in kw_contacts[:5]:
            console.print(f"    {c.full_name}")
        if len(kw_contacts) > 5:
            console.print(f"    ... and {len(kw_contacts) - 5} more")

        console.print()
        console.print("  Position: [bold]s[/bold]=start  [bold]e[/bold]=end  [bold]r[/bold]=remove  [bold]k[/bold]=keep position")
        pos = Prompt.ask("  Position").strip().lower()
        if pos not in ("s", "e", "r", "k"):
            console.print("[red]  Invalid.[/red]")
            continue

        casing = "k"
        if pos != "r":
            console.print("  Casing: [bold]u[/bold]=UPPER  [bold]l[/bold]=lower  [bold]t[/bold]=Title  [bold]k[/bold]=keep")
            casing = Prompt.ask("  Casing", default="k").strip().lower()
            if casing not in ("u", "l", "t", "k"):
                casing = "k"

        n = _apply_keyword_change(kw_contacts, keyword, pos, casing)
        console.print(f"  [green]✓ Applied to {n} contacts[/green]")
        for c in kw_contacts[:3]:
            console.print(f"    → {c.full_name}")
        console.print()


def _titlecase_phase(contacts: list[Contact]) -> None:
    changes = [
        (c, c.full_name, title_case_name(c.full_name))
        for c in contacts
        if c.full_name and title_case_name(c.full_name) != c.full_name
    ]
    if not changes:
        return

    console.print()
    console.rule("Title Case")
    console.print(f"  {len(changes)} names need title-casing:")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, box=None, padding=(0, 1))
    table.add_column("Before", min_width=25)
    table.add_column("After", min_width=25)
    for _, old, new in changes[:20]:
        table.add_row(old, new)
    if len(changes) > 20:
        table.add_row(f"  ... and {len(changes) - 20} more", "")
    console.print(table)
    console.print()

    raw = Prompt.ask("Apply title case to all? [y/n]", default="y").strip().lower()
    if raw == "y":
        for c, _, new in changes:
            c.full_name = new
        console.print(f"  [green]✓ Updated {len(changes)} names[/green]")


def run_session(file_paths: list[str], output: str) -> None:
    console.print()
    console.rule("[bold]Contact Sorter[/bold]")
    console.print()

    contacts: list[Contact] = []
    for fp in file_paths:
        with console.status(f"Loading {Path(fp).name}..."):
            batch = parse_vcf(fp)
        console.print(f"  {Path(fp).name}: {len(batch)} contacts")
        contacts.extend(batch)

    console.print(f"  [bold]Total: {len(contacts)} contacts[/bold]")

    if not contacts:
        console.print("[red]No contacts found.[/red]")
        return

    console.print()
    with console.status("Grouping by name..."):
        name_groups = group_by_name(contacts)
    console.print(f"  By name:   {len(name_groups)} group(s) found")

    with console.status("Grouping by phone..."):
        phone_groups_initial = group_by_phone(contacts)
    console.print(f"  By phone:  {len(phone_groups_initial)} group(s) found")

    if not name_groups and not phone_groups_initial:
        console.print()
        console.print("[green]No duplicates found — contacts are already clean.[/green]")
        _do_export(contacts, output)
        return

    if name_groups:
        console.print()
        console.rule(f"[bold]Phase 1 / 3 — Merge by Name ({len(name_groups)} groups)[/bold]")

        while True:
            decisions = _review_groups(name_groups, "same name")
            _show_summary(name_groups, decisions)
            raw = Prompt.ask("  c=confirm and continue / b=back to review", default="c").strip().lower()
            if raw == "c":
                contacts = _apply_merges(contacts, name_groups, decisions)
                console.print(f"  [green]✓ Applied {len(decisions)} merge(s)[/green]")
                break

    with console.status("Re-checking phone groups..."):
        phone_groups = group_by_phone(contacts)

    if phone_groups:
        console.print()
        console.rule(f"[bold]Phase 2 / 3 — Merge by Phone ({len(phone_groups)} groups)[/bold]")

        while True:
            decisions = _review_groups(phone_groups, "same number")
            _show_summary(phone_groups, decisions)
            raw = Prompt.ask("  c=confirm and continue / b=back to review", default="c").strip().lower()
            if raw == "c":
                contacts = _apply_merges(contacts, phone_groups, decisions)
                console.print(f"  [green]✓ Applied {len(decisions)} merge(s)[/green]")
                break
    else:
        console.print()
        console.print("  [green]No phone-based duplicates remaining.[/green]")

    _keyword_phase(contacts)
    _titlecase_phase(contacts)

    _do_export(contacts, output)


def _do_export(contacts: list[Contact], output: str) -> None:
    console.print()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with console.status(f"Exporting to {output}..."):
        count = export_vcf(contacts, path)
    console.print(f"[green]✓ Exported {count} contacts → {output}[/green]")
    console.print()
