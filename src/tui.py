"""Interactive TUI for contact sorting — rebuilt for real use."""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, DataTable, Button,
    Input, RichLog, Checkbox, Select, Label,
)
from textual.containers import Horizontal, Vertical

from .vcards import load_all, Contact
from .matcher import find_duplicates, DuplicateCluster
from .merger import merge_cluster, preview_name
from .exporter import export_vcf
from .normalize import (
    title_case_name, clean_name, normalize_name_case,
    normalize_phone, _PREFIXES, _SUFFIXES,
)


class MainMenu(Screen):
    BINDINGS = [
        Binding("1", "action_view", "View"),
        Binding("2", "action_merge", "Merge"),
        Binding("3", "action_clean", "Clean"),
        Binding("4", "action_export", "Export"),
        Binding("q", "action_quit", "Quit"),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            by_file: dict[str, int] = {}
            for c in self.contacts:
                by_file[c.source_file] = by_file.get(c.source_file, 0) + 1
            stats_lines = []
            for f, n in by_file.items():
                stats_lines.append(f"  {f}: {n}")
            stats_lines.append(f"  Total: {len(self.contacts)}")
            yield Static(
                "[bold]Contact Sorter[/bold]\n"
                + "\n".join(stats_lines)
                + "\n\n"
                "[bold]Choose:[/bold]\n"
                "  [cyan]1[/cyan] View & search contacts\n"
                "  [cyan]2[/cyan] Find & merge duplicates\n"
                "  [cyan]3[/cyan] Clean & rename names\n"
                "  [cyan]4[/cyan] Export to VCF\n"
                "  [cyan]q[/cyan] Quit",
                id="menu",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu").focus()

    def action_view(self) -> None:
        self.app.push_screen(ViewScreen(self.contacts))

    def action_merge(self) -> None:
        self.app.push_screen(MergeScreen(self.contacts))

    def action_clean(self) -> None:
        self.app.push_screen(CleanScreen(self.contacts))

    def action_export(self) -> None:
        self.app.push_screen(ExportScreen(self.contacts))

    def action_quit(self) -> None:
        self.app.exit()


class ViewScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("f", "focus_search", "Search", show=True),
        Binding("a", "select_all", "Select All", show=True),
        Binding("n", "select_none", "Deselect", show=True),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts
        self.filtered: list[Contact] = contacts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="view"):
            yield Input(placeholder="Search contacts... (name, phone, email, org)", id="search", classes="search-bar")
            yield Static("", id="count-label")
            yield DataTable(id="table", cursor_type="row")
            with Horizontal(id="actions"):
                yield Button("Back (esc)", id="back")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table")
        table.add_columns("Name", "Phones", "Emails", "Org", "Source")
        self._populate_table(self.contacts)
        self.query_one("#search").focus()

    def _populate_table(self, contacts: list[Contact]) -> None:
        table = self.query_one("#table")
        table.clear()
        for c in contacts:
            phones = ", ".join(p.number for p in c.phones) or "-"
            emails = ", ".join(e.address for e in c.emails) or "-"
            table.add_row(c.full_name or "(no name)", phones, emails, c.org or "-", c.source_file)
        self.query_one("#count-label").update(f"Showing {len(contacts)} of {len(self.contacts)} contacts")

    def on_input_changed(self, event: Input.Changed) -> None:
        q = event.value.lower().strip()
        if not q:
            self.filtered = self.contacts
        else:
            self.filtered = [
                c for c in self.contacts
                if q in c.full_name.lower()
                or q in c.org.lower()
                or q in c.note.lower()
                or any(q in p.number for p in c.phones)
                or any(q in e.address.lower() for e in c.emails)
            ]
        self._populate_table(self.filtered)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_focus_search(self) -> None:
        self.query_one("#search").focus()


class MergeScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "approve", "Approve"),
        Binding("s", "skip", "Skip"),
        Binding("r", "rename", "Rename"),
        Binding("n", "next", "Next"),
        Binding("p", "prev", "Prev"),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts
        self.clusters: list[DuplicateCluster] = []
        self.idx = 0
        self.merged: list[Contact] = []
        self.skipped_clusters: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="merge"):
            yield Static("", id="status")
            yield Static("", id="cluster-view")
            yield Static("", id="preview")
            yield Static("", id="log")
            with Horizontal(id="btns"):
                yield Button("Approve (a)", variant="success", id="btn-approve")
                yield Button("Skip (s)", variant="default", id="btn-skip")
                yield Button("Rename (r)", variant="warning", id="btn-rename")
                yield Button("Next (n)", id="btn-next")
                yield Button("Prev (p)", id="btn-prev")
                yield Button("Back (esc)", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.clusters = find_duplicates(self.contacts)
        if not self.clusters:
            self.query_one("#status").update("[green]No duplicates found[/green]")
            return
        self._show()

    def _show(self) -> None:
        if self.idx >= len(self.clusters):
            self.query_one("#status").update("[green]All done![/green]")
            self.query_one("#cluster-view").update("")
            self.query_one("#preview").update("")
            self._summary()
            return
        c = self.clusters[self.idx]
        conf = c.confidence
        color = "green" if conf >= 0.95 else "yellow" if conf >= 0.80 else "red"
        self.query_one("#status").update(
            f"[bold]Cluster {self.idx+1}/{len(self.clusters)}[/bold]  "
            f"[{color}]{conf:.0%} confidence[/{color}]"
        )
        lines = []
        for i, contact in enumerate(c.contacts):
            phones = ", ".join(f"{p.number} ({p.type})" for p in contact.phones) or "none"
            emails = ", ".join(e.address for e in contact.emails) or "none"
            lines.append(f"[bold cyan]#{i+1}[/bold cyan] {contact.full_name or '(no name)'}")
            lines.append(f"     Phone: {phones}  |  Email: {emails}")
            if contact.org:
                lines.append(f"     Org: {contact.org}")
            lines.append(f"     From: {contact.source_file}")
        signals = ", ".join(f"{s.kind}" for s in c.signals)
        lines.append(f"\n[dim]Signals: {signals}[/dim]")
        proposed = preview_name(c)
        lines.append(f"[bold green]→ Merged name: {proposed}[/bold green]")
        self.query_one("#cluster-view").update("\n".join(lines))
        self.query_one("#preview").update("")
        self.query_one("#log").update("")

    def _summary(self) -> None:
        n = len(self.merged)
        s = len(self.skipped_clusters)
        self.query_one("#cluster-view").update(
            f"[bold]Merged: {n}[/bold]  |  [dim]Skipped: {s}[/dim]"
        )

    def action_approve(self) -> None:
        if self.idx >= len(self.clusters):
            return
        cluster = self.clusters[self.idx]
        merged = merge_cluster(cluster)
        self.merged.append(merged)
        self.query_one("#log").update(f"[green]✓ Merged as: {merged.full_name}[/green]")
        self.idx += 1
        self._show()

    def action_skip(self) -> None:
        if self.idx >= len(self.clusters):
            return
        self.skipped_clusters.append(self.idx)
        self.query_one("#log").update("[dim]Skipped[/dim]")
        self.idx += 1
        self._show()

    def action_rename(self) -> None:
        if self.idx >= len(self.clusters):
            return
        self.app.push_screen(RenameScreen(self.clusters[self.idx], self))

    def action_next(self) -> None:
        if self.idx < len(self.clusters) - 1:
            self.idx += 1
            self._show()

    def action_prev(self) -> None:
        if self.idx > 0:
            self.idx -= 1
            self._show()

    def action_back(self) -> None:
        self.app.pop_screen()


class RenameScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, cluster: DuplicateCluster, parent: MergeScreen):
        super().__init__()
        self.cluster = cluster
        self.parent = parent

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="rename"):
            yield Static("[bold]Current names:[/bold]")
            for c in self.cluster.contacts:
                yield Static(f"  {c.full_name or '(no name)'}")
            yield Static("")
            yield Label("[bold]Enter the correct name:[/bold]")
            yield Input(placeholder="Type name...", id="name-input")
            with Horizontal():
                yield Button("Confirm", variant="success", id="confirm")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#name-input").focus()

    def _apply(self, name: str) -> None:
        if not name:
            return
        merged = merge_cluster(self.cluster, chosen_name=name)
        self.parent.merged.append(merged)
        self.parent.query_one("#log").update(f"[green]✓ Merged as: {merged.full_name}[/green]")
        self.parent.idx += 1
        self.parent._show()
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self._apply(self.query_one("#name-input").value.strip())
        elif event.button.id == "cancel":
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply(event.value.strip())


class CleanScreen(Screen):
    """Find-and-replace style name cleaning with full control."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+a", "apply", "Apply Changes"),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts
        self.changes: list[tuple[Contact, str, str]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="clean"):
            yield Static("[bold]Clean & Rename Contacts[/bold]\n")

            yield Label("[bold]Find text in names:[/bold]")
            yield Input(placeholder="e.g. Mr.  or  RAJESH  or  (Home)", id="find-input")

            yield Label("[bold]Replace with (leave empty to remove):[/bold]")
            yield Input(placeholder="replacement text...", id="replace-input", value="")

            yield Static("")
            with Horizontal():
                yield Checkbox("Case-sensitive", id="case-sensitive", value=False)
                yield Checkbox("Regex mode", id="regex-mode", value=False)
                yield Checkbox("Title-case result", id="title-case", value=False)

            yield Static("")
            with Horizontal():
                yield Button("Preview (p)", variant="primary", id="preview-btn")
                yield Button("Apply to All (Ctrl+A)", variant="success", id="apply-btn")
                yield Button("Quick: Strip Honorifics", variant="warning", id="strip-btn")
                yield Button("Quick: Title-Case All", variant="warning", id="titlecase-btn")
                yield Button("Quick: Remove Brackets", variant="warning", id="brackets-btn")
                yield Button("Back (esc)", id="back")

            yield Static("", id="count-label")
            yield RichLog(id="preview-log", highlight=True)
        yield Footer()

    def _find_matches(self) -> list[Contact]:
        find_text = self.query_one("#find-input").value
        if not find_text:
            return []
        case_sensitive = self.query_one("#case-sensitive").value
        use_regex = self.query_one("#regex-mode").value

        matches = []
        for c in self.contacts:
            name = c.full_name
            if not name:
                continue
            if use_regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                if re.search(find_text, name, flags):
                    matches.append(c)
            else:
                hay = name if case_sensitive else name.lower()
                needle = find_text if case_sensitive else find_text.lower()
                if needle in hay:
                    matches.append(c)
        return matches

    def _compute_replacements(self) -> list[tuple[Contact, str, str]]:
        find_text = self.query_one("#find-input").value
        replace_text = self.query_one("#replace-input").value
        case_sensitive = self.query_one("#case-sensitive").value
        use_regex = self.query_one("#regex-mode").value
        do_title = self.query_one("#title-case").value

        if not find_text:
            return []

        changes = []
        for c in self.contacts:
            name = c.full_name
            if not name:
                continue
            if use_regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                new_name = re.sub(find_text, replace_text, name, flags=flags)
            else:
                if case_sensitive:
                    new_name = name.replace(find_text, replace_text)
                else:
                    pattern = re.compile(re.escape(find_text), re.IGNORECASE)
                    new_name = pattern.sub(replace_text, name)
            new_name = re.sub(r"\s+", " ", new_name).strip()
            if do_title:
                new_name = title_case_name(new_name)
            if new_name != name:
                changes.append((c, name, new_name))
        return changes

    def _show_preview(self, changes: list[tuple[Contact, str, str]]) -> None:
        log = self.query_one("#preview-log")
        log.clear()
        self.query_one("#count-label").update(f"[bold]{len(changes)} contacts would be changed[/bold]")
        if not changes:
            log.write("[dim]No matches found.[/dim]")
            return
        for c, old, new in changes:
            phones = ", ".join(p.number for p in c.phones) or ""
            log.write(f"  [red]{old}[/red]  →  [green]{new}[/green]  [dim]{phones}[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preview-btn":
            self._show_preview(self._compute_replacements())
        elif event.button.id == "apply-btn":
            self._apply_all()
        elif event.button.id == "strip-btn":
            self._quick_strip()
        elif event.button.id == "titlecase-btn":
            self._quick_titlecase()
        elif event.button.id == "brackets-btn":
            self._quick_brackets()
        elif event.button.id == "back":
            self.app.pop_screen()

    def _apply_all(self) -> None:
        changes = self._compute_replacements()
        log = self.query_one("#preview-log")
        if not changes:
            log.write("[dim]Nothing to change.[/dim]")
            return
        count = 0
        for c, old, new in changes:
            c.full_name = new
            count += 1
        log.write(f"\n[green]✓ Applied {count} changes[/green]")
        self.query_one("#count-label").update(f"[green]{count} names updated[/green]")
        self.query_one("#find-input").value = ""
        self.query_one("#replace-input").value = ""

    def _quick_strip(self) -> None:
        all_honorifics = sorted(_PREFIXES | _SUFFIXES, key=len, reverse=True)
        log = self.query_one("#preview-log")
        log.clear()
        count = 0
        for c in self.contacts:
            old = c.full_name
            if not old:
                continue
            new = clean_name(old)
            if new != old:
                c.full_name = new
                phones = ", ".join(p.number for p in c.phones) or ""
                log.write(f"  [red]{old}[/red]  →  [green]{new}[/green]  [dim]{phones}[/dim]")
                count += 1
        log.write(f"\n[green]✓ Stripped honorifics from {count} contacts[/green]")
        self.query_one("#count-label").update(f"[green]{count} names cleaned[/green]")

    def _quick_titlecase(self) -> None:
        log = self.query_one("#preview-log")
        log.clear()
        count = 0
        for c in self.contacts:
            old = c.full_name
            if not old:
                continue
            new = title_case_name(old)
            if new != old:
                c.full_name = new
                phones = ", ".join(p.number for p in c.phones) or ""
                log.write(f"  [red]{old}[/red]  →  [green]{new}[/green]  [dim]{phones}[/dim]")
                count += 1
        log.write(f"\n[green]✓ Title-cased {count} contacts[/green]")
        self.query_one("#count-label").update(f"[green]{count} names updated[/green]")

    def _quick_brackets(self) -> None:
        log = self.query_one("#preview-log")
        log.clear()
        count = 0
        for c in self.contacts:
            old = c.full_name
            if not old:
                continue
            new = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", old)
            new = re.sub(r"\s+", " ", new).strip()
            new = title_case_name(new)
            if new != old:
                c.full_name = new
                phones = ", ".join(p.number for p in c.phones) or ""
                log.write(f"  [red]{old}[/red]  →  [green]{new}[/green]  [dim]{phones}[/dim]")
                count += 1
        log.write(f"\n[green]✓ Removed brackets from {count} contacts[/green]")
        self.query_one("#count-label").update(f"[green]{count} names updated[/green]")

    def action_apply(self) -> None:
        self._apply_all()

    def action_back(self) -> None:
        self.app.pop_screen()


class ExportScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="export"):
            yield Static(f"[bold]Export {len(self.contacts)} contacts to VCF[/bold]\n")
            yield Label("Output filename:")
            yield Input(value="merged_contacts.vcf", id="filename")
            with Horizontal():
                yield Button("Export", variant="success", id="export-btn")
                yield Button("Back (esc)", id="back")
            yield Static("", id="result")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-btn":
            name = self.query_one("#filename").value.strip() or "merged_contacts.vcf"
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            count = export_vcf(self.contacts, path)
            self.query_one("#result").update(f"[green]✓ Exported {count} contacts to {path}[/green]")
        elif event.button.id == "back":
            self.app.pop_screen()


class ContactSorterApp(App):
    TITLE = "Contact Sorter"
    SUB_TITLE = "merge · clean · organize"

    CSS = """
    Screen { background: $surface; }
    #main { padding: 1 2; }
    #menu { width: 100%; }
    .search-bar { width: 100%; margin: 0 0 1 0; }
    #table { height: 1fr; }
    #view { padding: 0 1; }
    #merge { padding: 0 2; }
    #clean { padding: 0 2; }
    #rename { padding: 1 2; }
    #export { padding: 1 2; }
    #cluster-view { height: auto; max-height: 18; }
    #preview-log { height: 12; border: solid $accent; margin: 1 0; }
    #btns Button { margin: 0 1; }
    #actions { padding: 1 0; }
    #count-label { padding: 0 0 0 0; }
    """

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self, file_paths: list[str]):
        super().__init__()
        self.file_paths = file_paths

    def on_mount(self) -> None:
        if self.file_paths:
            contacts = load_all(self.file_paths)
            self.push_screen(MainMenu(contacts))
        else:
            self.push_screen(FileLoadScreen())

    def action_quit(self) -> None:
        self.exit()


class FileLoadScreen(Screen):
    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="load"):
            yield Static("[bold]Contact Sorter[/bold]\n")
            yield Label("Enter VCF file paths (comma-separated):")
            yield Input(placeholder="/path/to/contacts.vcf", id="file-input")
            with Horizontal():
                yield Button("Load", variant="success", id="load-btn")
                yield Button("Quit", variant="error", id="quit-btn")
            yield Static("", id="load-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#file-input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "load-btn":
            self._load()
        elif event.button.id == "quit-btn":
            self.app.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._load()

    def _load(self) -> None:
        raw = self.query_one("#file-input").value.strip()
        if not raw:
            return
        paths = [p.strip() for p in raw.split(",") if p.strip()]
        valid = []
        for p in paths:
            if Path(p).exists():
                valid.append(p)
            else:
                self.query_one("#load-status").update(f"[red]Not found: {p}[/red]")
                return
        contacts = load_all(valid)
        self.app.push_screen(MainMenu(contacts))


def run_tui(file_paths: list[str]):
    app = ContactSorterApp(file_paths)
    app.run()
