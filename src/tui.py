"""Interactive TUI for contact sorting."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, DataTable, Button,
    OptionList, Label, Input, RichLog, Checkbox,
)
from textual.widgets._option_list import Option
from textual.containers import Horizontal, Vertical, Container

from .vcards import load_all, Contact
from .matcher import find_duplicates, DuplicateCluster
from .merger import merge_cluster, preview_name
from .exporter import export_vcf
from .normalize import title_case_name, clean_name, normalize_name_case


class LoadScreen(Screen):
    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self, file_paths: list[str]):
        super().__init__()
        self.file_paths = file_paths
        self.contacts: list[Contact] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("[bold cyan]Contact Sorter[/bold cyan]\n", id="title"),
            Static(f"Files: {', '.join(self.file_paths)}", id="file-info"),
            Button("Load & Continue", variant="primary", id="load-btn"),
            Button("Quit", variant="error", id="quit-btn"),
            id="load-area",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#load-btn").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "load-btn":
            self.contacts = load_all(self.file_paths)
            self.app.push_screen(MainMenu(self.contacts, self.file_paths))
        elif event.button.id == "quit-btn":
            self.app.exit()


class MainMenu(Screen):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "merge", "Merge"),
        Binding("2", "clean", "Clean Names"),
        Binding("3", "export", "Export"),
        Binding("4", "view", "View All"),
    ]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu-area"):
            yield Static(self._stats_text(), id="stats")
            yield Static("[bold]Operations:[/bold]\n")
            yield OptionList(
                Option("Find & merge duplicate contacts", id="merge"),
                Option("Clean names (fix case, strip honorifics)", id="clean"),
                Option("View all contacts", id="view"),
                Option("Export contacts to VCF", id="export"),
                Option("Load more files", id="load-more"),
                Option("Quit", id="quit"),
                id="menu-list",
            )
        yield Footer()

    def _stats_text(self) -> str:
        by_file: dict[str, int] = {}
        for c in self.contacts:
            by_file[c.source_file] = by_file.get(c.source_file, 0) + 1
        lines = ["[bold cyan]Loaded Contacts[/bold cyan]"]
        for f, count in by_file.items():
            lines.append(f"  {f}: {count}")
        lines.append(f"  [bold]Total: {len(self.contacts)}[/bold]")
        return "\n".join(lines)

    def on_mount(self) -> None:
        self.query_one("#menu-list").focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id == "merge":
            self.app.push_screen(MergeScreen(self.contacts, self.file_paths))
        elif option_id == "clean":
            self.app.push_screen(CleanScreen(self.contacts, self.file_paths))
        elif option_id == "view":
            self.app.push_screen(ViewScreen(self.contacts, self.file_paths))
        elif option_id == "export":
            self.app.push_screen(ExportScreen(self.contacts, self.file_paths))
        elif option_id == "load-more":
            self.app.push_screen(FilePickerScreen(self.contacts, self.file_paths))
        elif option_id == "quit":
            self.app.exit()


class MergeScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "approve", "Approve"),
        Binding("s", "skip", "Skip"),
        Binding("r", "rename", "Rename"),
        Binding("k", "keep", "Keep Separate"),
        Binding("n", "next_cluster", "Next"),
        Binding("p", "prev_cluster", "Prev"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths
        self.clusters: list[DuplicateCluster] = []
        self.merged_contacts: list[Contact] = []
        self.kept_contacts: list[Contact] = []
        self.current_idx = 0
        self.results_log: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="merge-area"):
            yield Static("Finding duplicates...", id="merge-status")
            yield Static("", id="cluster-info")
            yield Static("", id="cluster-entries")
            yield Static("", id="proposed-name")
            yield Static("", id="merge-log")
            with Horizontal(id="merge-actions"):
                yield Button("Approve (a)", variant="success", id="btn-approve")
                yield Button("Skip (s)", variant="default", id="btn-skip")
                yield Button("Rename (r)", variant="warning", id="btn-rename")
                yield Button("Keep Separate (k)", variant="error", id="btn-keep")
                yield Button("Next (n)", variant="default", id="btn-next")
                yield Button("Back to Menu (esc)", variant="default", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.clusters = find_duplicates(self.contacts)
        if not self.clusters:
            self.query_one("#merge-status").update("[green]No duplicates found![/green]")
            return
        self.query_one("#merge-status").update(
            f"[bold]Found {len(self.clusters)} clusters — use keys or buttons[/bold]"
        )
        self._show_cluster()

    def _show_cluster(self) -> None:
        if not self.clusters:
            self.query_one("#cluster-info").update("[green]All clusters reviewed![/green]")
            self.query_one("#cluster-entries").update("")
            self.query_one("#proposed-name").update("")
            return

        cluster = self.clusters[self.current_idx]
        conf = cluster.confidence
        conf_style = "green" if conf >= 0.95 else "yellow" if conf >= 0.80 else "red"
        conf_label = "HIGH" if conf >= 0.95 else "MED" if conf >= 0.80 else "LOW"

        self.query_one("#cluster-info").update(
            f"[bold]Cluster {self.current_idx + 1}/{len(self.clusters)}[/bold]  "
            f"[{conf_style}]confidence: {conf:.0%} ({conf_label})[/{conf_style}]"
        )

        lines = []
        for i, c in enumerate(cluster.contacts):
            lines.append(f"[bold cyan]Entry {i+1}:[/bold cyan] {c.full_name or '(no name)'}")
            phones = ", ".join(f"{p.number} ({p.type})" for p in c.phones) or "none"
            emails = ", ".join(e.address for e in c.emails) or "none"
            lines.append(f"  Phones: {phones}")
            lines.append(f"  Emails: {emails}")
            if c.org:
                lines.append(f"  Org: {c.org}")
            lines.append(f"  Source: {c.source_file}")
            lines.append("")
        self.query_one("#cluster-entries").update("\n".join(lines))

        proposed = preview_name(cluster)
        self.query_one("#proposed-name").update(
            f"[bold green]→ If merged: [white]{proposed}[/white][/bold green]"
        )

    def _advance(self) -> None:
        self.current_idx += 1
        if self.current_idx >= len(self.clusters):
            self.current_idx = len(self.clusters)
            self.query_one("#cluster-info").update("[green]All clusters reviewed![/green]")
            self.query_one("#cluster-entries").update("")
            self.query_one("#proposed-name").update("")
            self._show_summary()
        else:
            self._show_cluster()

    def _show_summary(self) -> None:
        total_out = len(self.contacts) - sum(len(c.contacts) for c in self.merged_contacts) + len(self.merged_contacts) + len(self.kept_contacts)
        lines = [
            f"[bold]Merged: {len(self.merged_contacts)}[/bold]",
            f"[bold]Kept separate: {len(self.kept_contacts)}[/bold]",
            f"[bold]Result: {total_out} contacts[/bold]",
        ]
        self.query_one("#merge-log").update("\n".join(lines))

    def _log_merge(self, cluster: DuplicateCluster, merged: Contact, action: str) -> None:
        self.results_log.append({
            "action": action,
            "entries": [(c.full_name, c.all_phone_strings) for c in cluster.contacts],
            "result": merged.full_name,
            "phones": merged.all_phone_strings,
            "emails": merged.all_email_strings,
        })

    def action_approve(self) -> None:
        if not self.clusters or self.current_idx >= len(self.clusters):
            return
        cluster = self.clusters[self.current_idx]
        merged = merge_cluster(cluster)
        self.merged_contacts.append(merged)
        self._log_merge(cluster, merged, "merged")
        self.query_one("#merge-log").update(f"[green]✓ Merged as: {merged.full_name}[/green]")
        self._advance()

    def action_skip(self) -> None:
        if not self.clusters or self.current_idx >= len(self.clusters):
            return
        self.query_one("#merge-log").update("[dim]Skipped[/dim]")
        self._advance()

    def action_keep(self) -> None:
        if not self.clusters or self.current_idx >= len(self.clusters):
            return
        cluster = self.clusters[self.current_idx]
        for c in cluster.contacts:
            self.kept_contacts.append(c)
        self.query_one("#merge-log").update("[yellow]Keeping separate[/yellow]")
        self._advance()

    def action_rename(self) -> None:
        if not self.clusters or self.current_idx >= len(self.clusters):
            return
        cluster = self.clusters[self.current_idx]
        self.app.push_screen(RenameScreen(cluster, self))

    def action_next_cluster(self) -> None:
        if self.current_idx < len(self.clusters) - 1:
            self.current_idx += 1
            self.query_one("#merge-log").update("")
            self._show_cluster()

    def action_prev_cluster(self) -> None:
        if self.current_idx > 0:
            self.current_idx -= 1
            self.query_one("#merge-log").update("")
            self._show_cluster()

    def action_back(self) -> None:
        self.app.pop_screen()


class RenameScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, cluster: DuplicateCluster, merge_screen: MergeScreen):
        super().__init__()
        self.cluster = cluster
        self.merge_screen = merge_screen

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="rename-area"):
            yield Static("[bold]Current names:[/bold]")
            for c in self.cluster.contacts:
                yield Static(f"  - {c.full_name or '(no name)'}")
            yield Static("")
            yield Static("[bold]Enter the correct name:[/bold]")
            yield Input(placeholder="Type the name...", id="name-input")
            with Horizontal():
                yield Button("Confirm", variant="success", id="confirm")
                yield Button("Cancel", variant="default", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#name-input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            name = self.query_one("#name-input").value.strip()
            if name:
                merged = merge_cluster(self.cluster, chosen_name=name)
                self.merge_screen.merged_contacts.append(merged)
                self.merge_screen._log_merge(self.cluster, merged, "renamed")
                self.merge_screen.query_one("#merge-log").update(
                    f"[green]✓ Merged as: {merged.full_name}[/green]"
                )
                self.merge_screen._advance()
                self.app.pop_screen()
        elif event.button.id == "cancel":
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if name:
            merged = merge_cluster(self.cluster, chosen_name=name)
            self.merge_screen.merged_contacts.append(merged)
            self.merge_screen._log_merge(self.cluster, merged, "renamed")
            self.merge_screen.query_one("#merge-log").update(
                f"[green]✓ Merged as: {merged.full_name}[/green]"
            )
            self.merge_screen._advance()
            self.app.pop_screen()


class CleanScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths
        self.changes_log: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="clean-area"):
            yield Static("[bold cyan]Name Cleanup[/bold cyan]\n")
            yield Checkbox("Title-case names (RAJESH → Rajesh)", id="fix-case", value=True)
            yield Checkbox("Strip honorifics (Mr./Mrs./Dr./Smt./Shri/Ji)", id="strip-honor", value=True)
            yield Static("")
            yield Button("Preview Changes", variant="primary", id="preview-btn")
            yield Button("Apply Changes", variant="success", id="apply-btn")
            yield Button("Back to Menu (esc)", variant="default", id="back-btn")
            yield Static("", id="clean-result")
            yield RichLog(id="clean-log", highlight=True)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "preview-btn":
            self._preview()
        elif event.button.id == "apply-btn":
            self._apply()
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def _get_flags(self) -> tuple[bool, bool]:
        fix_case = self.query_one("#fix-case").value
        strip_honor = self.query_one("#strip-honor").value
        return fix_case, strip_honor

    def _compute_changes(self) -> list[dict]:
        fix_case, strip_honor = self._get_flags()
        changes = []
        for c in self.contacts:
            old_name = c.full_name
            if fix_case and strip_honor:
                new_name = normalize_name_case(old_name)
            elif fix_case:
                new_name = title_case_name(old_name)
            elif strip_honor:
                new_name = clean_name(old_name)
            else:
                new_name = old_name
            if new_name != old_name:
                changes.append({
                    "before": old_name,
                    "after": new_name,
                    "phones": c.all_phone_strings,
                })
        return changes

    def _preview(self) -> None:
        changes = self._compute_changes()
        log = self.query_one("#clean-log")
        log.clear()
        if not changes:
            log.write("[dim]No changes needed — names are already clean.[/dim]")
            return
        log.write(f"[bold]{len(changes)} names would be changed:[/bold]\n")
        for ch in changes:
            phones = ", ".join(ch["phones"]) if ch["phones"] else ""
            log.write(f"  [red]{ch['before']}[/red] → [green]{ch['after']}[/green]  [dim]{phones}[/dim]")

    def _apply(self) -> None:
        fix_case, strip_honor = self._get_flags()
        log = self.query_one("#clean-log")
        changes = self._compute_changes()
        if not changes:
            log.write("[dim]Nothing to change.[/dim]")
            return
        count = 0
        for c in self.contacts:
            old_name = c.full_name
            if fix_case and strip_honor:
                c.full_name = normalize_name_case(old_name)
            elif fix_case:
                c.full_name = title_case_name(old_name)
            elif strip_honor:
                c.full_name = clean_name(old_name)
            if c.full_name != old_name:
                self.changes_log.append({"before": old_name, "after": c.full_name, "phones": c.all_phone_strings})
                count += 1
        self.query_one("#clean-result").update(f"[green]Applied {count} name fixes[/green]")
        log.write(f"\n[green]✓ Applied {count} name fixes[/green]")

    def action_back(self) -> None:
        self.app.pop_screen()


class ViewScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="view-area"):
            yield Static(f"[bold]All Contacts ({len(self.contacts)})[/bold]\n")
            table = DataTable(id="contacts-table")
            yield table
            yield Button("Back to Menu (esc)", variant="default", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#contacts-table")
        table.add_columns("Name", "Phones", "Emails", "Org", "Source")
        for c in self.contacts:
            phones = ", ".join(p.number for p in c.phones) or "-"
            emails = ", ".join(e.address for e in c.emails) or "-"
            table.add_row(c.full_name or "(no name)", phones, emails, c.org or "-", c.source_file)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()


class ExportScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="export-area"):
            yield Static("[bold cyan]Export Contacts[/bold cyan]\n")
            yield Static(f"Ready to export [bold]{len(self.contacts)}[/bold] contacts\n")
            yield Label("Output filename:")
            yield Input(value="merged_contacts.vcf", id="filename-input")
            yield Static("")
            with Horizontal():
                yield Button("Export", variant="success", id="export-btn")
                yield Button("Back to Menu (esc)", variant="default", id="back-btn")
            yield Static("", id="export-result")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-btn":
            filename = self.query_one("#filename-input").value.strip() or "merged_contacts.vcf"
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            count = export_vcf(self.contacts, output_path)
            self.query_one("#export-result").update(
                f"[green]✓ Exported {count} contacts to {output_path}[/green]"
            )
        elif event.button.id == "back-btn":
            self.app.pop_screen()


class FilePickerScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, contacts: list[Contact], file_paths: list[str]):
        super().__init__()
        self.contacts = contacts
        self.file_paths = file_paths

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="picker-area"):
            yield Static("[bold cyan]Load More VCF Files[/bold cyan]\n")
            yield Static("Current files:")
            for fp in self.file_paths:
                yield Static(f"  ✓ {fp}")
            yield Static("")
            yield Static("Enter a VCF file path to add:")
            yield Input(placeholder="/path/to/file.vcf", id="file-input")
            with Horizontal():
                yield Button("Add & Load", variant="success", id="add-btn")
                yield Button("Back to Menu (esc)", variant="default", id="back-btn")
            yield Static("", id="picker-result")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#file-input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            self._add_file()
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._add_file()

    def _add_file(self) -> None:
        path_str = self.query_one("#file-input").value.strip()
        if not path_str:
            return
        path = Path(path_str)
        if not path.exists():
            self.query_one("#picker-result").update(f"[red]File not found: {path}[/red]")
            return
        if path_str in self.file_paths:
            self.query_one("#picker-result").update("[yellow]File already loaded[/yellow]")
            return
        new_contacts = load_all([path])
        self.contacts.extend(new_contacts)
        self.file_paths.append(path_str)
        self.query_one("#picker-result").update(
            f"[green]✓ Loaded {len(new_contacts)} contacts from {path.name}[/green]"
        )
        self.query_one("#file-input").value = ""


class ContactSorterApp(App):
    TITLE = "Contact Sorter"
    SUB_TITLE = "Merge & deduplicate VCF contacts"

    CSS = """
    #load-area, #menu-area, #merge-area, #clean-area, #view-area, #export-area, #picker-area, #rename-area {
        padding: 1 2;
    }
    #title {
        text-align: center;
        padding: 1 0;
    }
    #cluster-entries {
        height: auto;
        max-height: 15;
    }
    #merge-actions {
        padding: 1 0;
    }
    #merge-actions Button {
        margin: 0 1;
    }
    #clean-log {
        height: 12;
        border: solid $accent;
        margin: 1 0;
    }
    #contacts-table {
        height: 1fr;
    }
    """

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self, file_paths: list[str]):
        super().__init__()
        self.file_paths = file_paths

    def on_mount(self) -> None:
        self.push_screen(LoadScreen(self.file_paths))


def run_tui(file_paths: list[str]):
    app = ContactSorterApp(file_paths)
    app.run()
