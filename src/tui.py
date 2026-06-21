"""Interactive TUI for contact sorting — focus on usability."""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, DataTable, Button,
    Input, RichLog, Checkbox, Label,
)
from textual.containers import Horizontal, Vertical
from textual import work

from .vcards import load_all, Contact
from .matcher import find_duplicates, DuplicateCluster
from .merger import merge_cluster, preview_name
from .exporter import export_vcf
from .normalize import (
    title_case_name, clean_name, normalize_name_case,
    _PREFIXES, _SUFFIXES,
)


HELP_BAR = (
    "[dim]Navigate: [bold]↑↓[/bold] scroll  |  "
    "[bold]Tab[/bold] switch focus  |  "
    "[bold]Enter[/bold] select  |  "
    "[bold]Esc[/bold] back  |  "
    "[bold]?[/bold] this help[/dim]"
)


class MainMenu(Screen):
    BINDINGS = [
        Binding("1", "go_view", "View Contacts"),
        Binding("2", "go_merge", "Merge Duplicates"),
        Binding("3", "go_clean", "Clean Names"),
        Binding("4", "go_export", "Export"),
        Binding("q", "quit", "Quit"),
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
            stats = "\n".join(f"  {f}: {n}" for f, n in by_file.items())
            yield Static(
                f"[bold]Contact Sorter[/bold]\n\n"
                f"{stats}\n"
                f"  [bold]Total: {len(self.contacts)}[/bold]\n",
            )
            yield Static(
                "[bold]What to do:[/bold]\n\n"
                "  [cyan]1[/cyan]  [bold]View & search[/bold] — browse all contacts, filter by text\n"
                "  [cyan]2[/cyan]  [bold]Merge duplicates[/bold] — find same person saved twice\n"
                "  [cyan]3[/cyan]  [bold]Clean names[/bold] — fix case, remove Mr./Ji, find & replace\n"
                "  [cyan]4[/cyan]  [bold]Export[/bold] — save cleaned contacts to VCF file\n"
                "  [cyan]q[/cyan]  Quit\n"
            )
        yield Footer()

    def action_go_view(self) -> None:
        self.app.push_screen(ViewScreen(self.contacts))

    def action_go_merge(self) -> None:
        self.app.push_screen(MergeScreen(self.contacts))

    def action_go_clean(self) -> None:
        self.app.push_screen(CleanScreen(self.contacts))

    def action_go_export(self) -> None:
        self.app.push_screen(ExportScreen(self.contacts))

    def action_quit(self) -> None:
        self.app.exit()


class ViewScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("escape", "unfocus_table", "Unfocus", show=False, priority=True),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts
        self.filtered: list[Contact] = contacts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="view"):
            yield Static("[bold]View Contacts[/bold]  [dim]— type to search, ↑↓ to scroll, Esc back[/dim]\n")
            yield Input(placeholder="Search by name, phone, email, or org...", id="search")
            yield Static("", id="count")
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table")
        table.add_columns("Name", "Phones", "Emails", "Org", "From")
        self._fill(self.contacts)
        self.query_one("#search").focus()

    def _fill(self, contacts: list[Contact]) -> None:
        table = self.query_one("#table")
        table.clear()
        for c in contacts:
            phones = ", ".join(p.number for p in c.phones) or "-"
            emails = ", ".join(e.address for e in c.emails) or "-"
            table.add_row(
                c.full_name or "(no name)",
                phones, emails,
                c.org or "-",
                c.source_file,
            )
        self.query_one("#count").update(
            f"[dim]{len(contacts)} of {len(self.contacts)} contacts[/dim]"
        )

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
        self._fill(self.filtered)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if row_idx < len(self.filtered):
            c = self.filtered[row_idx]
            self.app.push_screen(ContactDetailScreen(c))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_unfocus_table(self) -> None:
        table = self.query_one("#table")
        if table.has_focus:
            self.query_one("#search").focus()
        else:
            self.app.pop_screen()


class ContactDetailScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, contact: Contact):
        super().__init__()
        self.contact = contact

    def compose(self) -> ComposeResult:
        yield Header()
        c = self.contact
        lines = [
            f"[bold cyan]Name:[/bold cyan]     {c.full_name or '(no name)'}",
        ]
        if c.given_name or c.family_name:
            lines.append(f"[bold cyan]Given:[/bold cyan]    {c.given_name}")
            lines.append(f"[bold cyan]Family:[/bold cyan]   {c.family_name}")
        if c.org:
            lines.append(f"[bold cyan]Org:[/bold cyan]      {c.org}")
        if c.title:
            lines.append(f"[bold cyan]Title:[/bold cyan]    {c.title}")
        for p in c.phones:
            lines.append(f"[bold cyan]Phone:[/bold cyan]    {p.number} ({p.type})")
        for e in c.emails:
            lines.append(f"[bold cyan]Email:[/bold cyan]    {e.address} ({e.type})")
        if c.note:
            lines.append(f"[bold cyan]Note:[/bold cyan]    {c.note}")
        lines.append(f"[bold cyan]Source:[/bold cyan]   {c.source_file}")
        lines.append(f"[bold cyan]UID:[/bold cyan]      {c.uid}")
        yield Vertical(
            Static("\n".join(lines), id="detail"),
            Button("Back (esc)", id="back"),
            id="detail-area",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class MergeScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "approve", "Approve"),
        Binding("s", "skip", "Skip"),
        Binding("r", "rename", "Rename"),
        Binding("n", "next_cluster", "Next"),
        Binding("p", "prev_cluster", "Prev"),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts
        self.clusters: list[DuplicateCluster] = []
        self.idx = 0
        self.merged: list[Contact] = []
        self.skipped: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="merge"):
            yield Static("[bold]Merge Duplicates[/bold]  [dim]— a=approve  s=skip  r=rename  n/p=navigate  Esc=back[/dim]\n")
            yield Static("", id="status")
            yield Static("", id="body")
            yield Static("", id="log")
            with Horizontal(id="btns"):
                yield Button("✓ Approve (a)", variant="success", id="btn-yes")
                yield Button("✗ Skip (s)", variant="default", id="btn-skip")
                yield Button("✎ Rename (r)", variant="warning", id="btn-rename")
                yield Button("→ Next (n)", id="btn-next")
                yield Button("← Prev (p)", id="btn-prev")
                yield Button("← Back (esc)", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.clusters = find_duplicates(self.contacts)
        if not self.clusters:
            self.query_one("#status").update("[green]No duplicates found — your contacts are clean![/green]")
            return
        self._show()

    def _show(self) -> None:
        body = self.query_one("#body")
        log = self.query_one("#log")
        log.update("")

        if self.idx >= len(self.clusters):
            self.query_one("#status").update("[bold green]All clusters reviewed[/bold green]")
            n = len(self.merged)
            s = len(self.skipped)
            body.update(f"[bold]Merged: {n}[/bold]  |  [dim]Skipped: {s}[/dim]")
            return

        c = self.clusters[self.idx]
        conf = c.confidence
        color = "green" if conf >= 0.95 else "yellow" if conf >= 0.80 else "red"
        label = "HIGH" if conf >= 0.95 else "MED" if conf >= 0.80 else "LOW"

        self.query_one("#status").update(
            f"[bold]Cluster {self.idx+1} of {len(self.clusters)}[/bold]  "
            f"[{color}]confidence: {conf:.0%} ({label})[/{color}]"
        )

        lines = []
        for i, contact in enumerate(c.contacts):
            phones = ", ".join(f"{p.number} ({p.type})" for p in contact.phones) or "none"
            emails = ", ".join(e.address for e in contact.emails) or "none"
            lines.append(f"[bold cyan]#{i+1}[/bold cyan]  {contact.full_name or '(no name)'}")
            lines.append(f"      Phone: {phones}")
            lines.append(f"      Email: {emails}")
            if contact.org:
                lines.append(f"      Org:   {contact.org}")
            lines.append(f"      From:  {contact.source_file}")
            lines.append("")

        signals = ", ".join(s.kind for s in c.signals)
        lines.append(f"[dim]Matched by: {signals}[/dim]")

        proposed = preview_name(c)
        lines.append(f"\n[bold green]→ If merged, name will be: {proposed}[/bold green]")

        body.update("\n".join(lines))

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
        self.skipped.append(self.idx)
        self.query_one("#log").update("[dim]Skipped[/dim]")
        self.idx += 1
        self._show()

    def action_rename(self) -> None:
        if self.idx >= len(self.clusters):
            return
        self.app.push_screen(RenameScreen(self.clusters[self.idx], self))

    def action_next_cluster(self) -> None:
        if self.idx < len(self.clusters) - 1:
            self.idx += 1
            self._show()

    def action_prev_cluster(self) -> None:
        if self.idx > 0:
            self.idx -= 1
            self._show()

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "btn-yes": self.action_approve,
            "btn-skip": self.action_skip,
            "btn-rename": self.action_rename,
            "btn-next": self.action_next_cluster,
            "btn-prev": self.action_prev_cluster,
            "btn-back": self.action_back,
        }
        if event.button.id in actions:
            actions[event.button.id]()


class RenameScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, cluster: DuplicateCluster, parent: MergeScreen):
        super().__init__()
        self.cluster = cluster
        self.parent = parent

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="rename"):
            yield Static("[bold]Rename Contact[/bold]\n")
            yield Static("[dim]Current names in this cluster:[/dim]")
            for c in self.cluster.contacts:
                yield Static(f"  • {c.full_name or '(no name)'}")
            yield Static("")
            yield Label("[bold]Type the correct name:[/bold]")
            yield Input(placeholder="Enter name...", id="name-input")
            with Horizontal():
                yield Button("✓ Confirm", variant="success", id="confirm")
                yield Button("← Cancel (esc)", id="cancel")
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

    def action_back(self) -> None:
        self.app.pop_screen()


class CleanScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, contacts: list[Contact]):
        super().__init__()
        self.contacts = contacts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="clean"):
            yield Static("[bold]Clean & Rename Contacts[/bold]  [dim]— find text, replace across all matches[/dim]\n")

            yield Static("[bold]Find:[/bold]")
            yield Input(placeholder="text to find in names... (e.g. Mr.  or  RAJESH  or  (Home))", id="find")

            yield Static("[bold]Replace with:[/bold]  [dim](leave empty to remove)[/dim]")
            yield Input(placeholder="replacement...", id="replace", value="")

            yield Static("")
            with Horizontal():
                yield Checkbox("Case-sensitive", id="case-sen")
                yield Checkbox("Regex", id="regex")
                yield Checkbox("Title-case result", id="titlecase")

            yield Static("")
            with Horizontal(id="action-btns"):
                yield Button("🔍 Preview", variant="primary", id="preview")
                yield Button("✓ Apply to All", variant="success", id="apply")
                yield Button("⚡ Strip Mr./Mrs./Ji", variant="warning", id="strip")
                yield Button("⚡ Title-Case All", variant="warning", id="title")
                yield Button("⚡ Remove (brackets)", variant="warning", id="brackets")
                yield Button("← Back (esc)", id="back")

            yield Static("", id="result-count")
            yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    def _find_matches(self) -> list[tuple[Contact, str, str]]:
        find_text = self.query_one("#find").value
        replace_text = self.query_one("#replace").value
        case_sensitive = self.query_one("#case-sen").value
        use_regex = self.query_one("#regex").value
        do_title = self.query_one("#titlecase").value

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

    def _show_preview(self) -> None:
        changes = self._find_matches()
        log = self.query_one("#log")
        log.clear()
        self.query_one("#result-count").update(f"[bold]{len(changes)} contacts would change[/bold]")
        if not changes:
            log.write("[dim]No matches found. Try different text.[/dim]")
            return
        for c, old, new in changes:
            phones = ", ".join(p.number for p in c.phones) or ""
            log.write(f"  [red]{old}[/red]  →  [green]{new}[/green]  [dim]{phones}[/dim]")

    def _apply(self) -> None:
        changes = self._find_matches()
        log = self.query_one("#log")
        if not changes:
            log.write("[dim]Nothing to change.[/dim]")
            return
        for c, old, new in changes:
            c.full_name = new
        count = len(changes)
        log.write(f"\n[green]✓ Updated {count} contacts[/green]")
        self.query_one("#result-count").update(f"[green]{count} names updated[/green]")
        self.query_one("#find").value = ""
        self.query_one("#replace").value = ""

    def _strip_honorifics(self) -> None:
        log = self.query_one("#log")
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
        self.query_one("#result-count").update(f"[green]{count} cleaned[/green]")

    def _titlecase_all(self) -> None:
        log = self.query_one("#log")
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
        self.query_one("#result-count").update(f"[green]{count} updated[/green]")

    def _remove_brackets(self) -> None:
        log = self.query_one("#log")
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
        self.query_one("#result-count").update(f"[green]{count} updated[/green]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "preview": self._show_preview,
            "apply": self._apply,
            "strip": self._strip_honorifics,
            "title": self._titlecase_all,
            "brackets": self._remove_brackets,
            "back": self.app.pop_screen,
        }
        if event.button.id in actions:
            actions[event.button.id]()

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
            yield Static(f"[bold]Export {len(self.contacts)} contacts[/bold]\n")
            yield Label("Output filename:")
            yield Input(value="merged_contacts.vcf", id="filename")
            with Horizontal():
                yield Button("✓ Export", variant="success", id="export-btn")
                yield Button("← Back (esc)", id="back")
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
            yield Static("", id="status")
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
                self.query_one("#status").update(f"[red]Not found: {p}[/red]")
                return
        contacts = load_all(valid)
        self.app.push_screen(MainMenu(contacts))


class ContactSorterApp(App):
    TITLE = "Contact Sorter"
    SUB_TITLE = "merge · clean · organize"

    CSS = """
    Screen { background: $surface; }
    #main { padding: 1 2; }
    #view { padding: 0 1; }
    #view Input { margin: 0 0 1 0; }
    #table { height: 1fr; }
    #merge { padding: 0 2; }
    #clean { padding: 0 2; }
    #clean Input { margin: 0 0 0 0; }
    #rename { padding: 1 2; }
    #export { padding: 1 2; }
    #detail-area { padding: 1 2; }
    #body { height: auto; max-height: 20; }
    #log { height: 10; border: solid $accent; margin: 1 0; }
    #btns Button { margin: 0 1; }
    #action-btns Button { margin: 0 1; }
    #result-count { padding: 0 0 0 0; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]

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

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


class HelpScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back"), Binding("?", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(
                "[bold]Keyboard Shortcuts[/bold]\n\n"
                "[bold cyan]Global:[/bold cyan]\n"
                "  q        Quit\n"
                "  ?        This help\n"
                "  Esc      Back / previous screen\n"
                "  Tab      Switch focus between widgets\n"
                "  ↑↓       Scroll lists and tables\n"
                "  Enter    Select highlighted item\n\n"
                "[bold cyan]Merge Screen:[/bold cyan]\n"
                "  a        Approve merge\n"
                "  s        Skip this cluster\n"
                "  r        Rename (type custom name)\n"
                "  n        Next cluster\n"
                "  p        Previous cluster\n\n"
                "[bold cyan]View Screen:[/bold cyan]\n"
                "  Type     Search/filter contacts\n"
                "  Click    View contact details\n"
                "  Esc      Back to menu\n\n"
                "[bold cyan]Clean Screen:[/bold cyan]\n"
                "  Enter text in Find box\n"
                "  Click Preview to see changes\n"
                "  Click Apply to commit\n"
                "  Or use quick-action buttons\n",
                id="help-text",
            ),
            Button("← Back", id="back"),
            id="help-area",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


def run_tui(file_paths: list[str]):
    app = ContactSorterApp(file_paths)
    app.run()
