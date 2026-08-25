#!/usr/bin/env python3
import subprocess
import json
import os
import sys
import re
import time
from textual.app import App, ComposeResult
from textual.widgets import Footer, DataTable, Static, Label, Input, Log, TextArea
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual import work
import logging

_log = logging.getLogger("fire_tui")
_log_handler = logging.FileHandler("/tmp/fire_tui.log")
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_log.addHandler(_log_handler)
_log.setLevel(logging.WARNING)

PREFIX = "fire-"
TUNNEL_DIR = "/tmp/fire-tunnels"

class ConfigEditorModal(ModalScreen):
    def __init__(self, svc_name, app_name):
        super().__init__()
        self.svc_name = svc_name
        self.app_name = app_name
        self.file_path = f"/etc/systemd/system/{svc_name}"

    def compose(self) -> ComposeResult:
        with Vertical(id="config_container"):
            yield Label(f"Editing Config: {self.app_name} [white](Ctrl+S to save, ESC to cancel)[/]", id="config_title")
            yield TextArea(id="config_edit", language="ini")
            yield Label("Press ESC to Cancel | Ctrl+S to Save", id="config_footer")

    def on_mount(self) -> None:
        text_area = self.query_one("#config_edit", TextArea)
        try:
            with open(self.file_path, "r") as f:
                content = f.read()
                text_area.load_text(content)
        except Exception as e:
            self.notify(f"Error reading config: {e}", severity="error")
        text_area.focus()

    def on_key(self, event) -> None:
        if event.key == "escape": self.app.pop_screen()
        elif event.key == "ctrl+s":
            self.save_config()

    def save_config(self) -> None:
        text_area = self.query_one("#config_edit", TextArea)
        try:
            content = text_area.text
            with open(self.file_path, "w") as f:
                f.write(content)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            self.notify(f"Config saved and reloaded for {self.app_name}")
            self.app.pop_screen()
        except Exception as e:
            self.notify(f"Error saving config: {e}", severity="error")

class ConfirmationModal(ModalScreen):
    def __init__(self, action_name, targets, callback):
        super().__init__()
        self.action_name = action_name
        self.targets = targets
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_container"):
            yield Label(f"⚠️ Confirm [bold red]{self.action_name}[/]", id="confirm_title")
            yield Label(f"Are you sure you want to {self.action_name.lower()} these {len(self.targets)} processes?", id="confirm_text")
            yield Log(id="confirm_list")
            with Horizontal(id="confirm_buttons"):
                yield Static("[bold green][Y][/] Yes", id="btn_yes")
                yield Static("[bold red][N][/] No", id="btn_no")

    def on_mount(self) -> None:
        log = self.query_one("#confirm_list", Log)
        for t in self.targets: log.write(f" - {t}\n")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.app.pop_screen()
            self.callback()
        elif event.key in ("n", "escape"):
            self.app.pop_screen()

class ResourceLimitsModal(ModalScreen):
    def __init__(self, svc_name, app_name):
        super().__init__()
        self.svc_name = svc_name
        self.app_name = app_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_container"):
            yield Label(f"⚙️ Resource Limits: {self.app_name}", id="confirm_title")
            yield Label("Memory Limit (e.g. 500M, 1G, or empty for none):", id="confirm_text_mem")
            yield Input(placeholder="Memory Limit", id="mem_input")
            yield Label("CPU Quota (e.g. 50%, 100%, or empty for none):", id="confirm_text_cpu")
            yield Input(placeholder="CPU Quota", id="cpu_input")
            with Horizontal(id="confirm_buttons"):
                yield Static("[bold green][ENTER][/] Save", id="btn_yes")
                yield Static("[bold red][ESC][/] Cancel", id="btn_no")

    def on_mount(self) -> None:
        self.query_one("#mem_input").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.save_limits()

    def save_limits(self) -> None:
        mem = self.query_one("#mem_input", Input).value.strip()
        cpu = self.query_one("#cpu_input", Input).value.strip()
        
        args = ["systemctl", "set-property", self.svc_name]
        
        if mem: 
            args.append(f"MemoryMax={mem}")
            args.append("MemorySwapMax=infinity")
        else: 
            args.append("MemoryMax=infinity")
            args.append("MemorySwapMax=infinity")
        
        if cpu: args.append(f"CPUQuota={cpu}")
        else: args.append("CPUQuota=") 
        
        try:
            subprocess.run(args, check=True, capture_output=True)
            self.notify(f"Resource limits updated for {self.app_name}")
            self.app.pop_screen()
        except subprocess.CalledProcessError as e:
            self.notify(f"Failed to set limits: {e.stderr.decode()}", severity="error")

    def on_key(self, event) -> None:
        if event.key == "escape": self.app.pop_screen()
        elif event.key == "enter": self.save_limits()

class LogModal(ModalScreen):
    def __init__(self, svc_name, app_name):
        super().__init__()
        self.svc_name = svc_name
        self.app_name = app_name

    def compose(self) -> ComposeResult:
        with Vertical(id="log_container"):
            yield Label(f"Live Logs: {self.app_name} [white](Press ESC to close)[/]", id="log_title")
            yield Log(id="log_view", highlight=True)
            yield Label("Press ESC to Close", id="log_footer")

    def on_mount(self) -> None:
        self.stream_logs()

    @work(exclusive=True, thread=True)
    def stream_logs(self) -> None:
        log_view = self.query_one("#log_view", Log)
        try:
            process = subprocess.Popen(
                ["journalctl", "-u", self.svc_name, "-f", "-n", "100", "--no-pager"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            for line in iter(process.stdout.readline, ""):
                if not self.is_running:
                    process.terminate()
                    break
                clean_line = line.split(": ", 1)[-1] if ": " in line else line
                self.app.call_from_thread(log_view.write, clean_line)
        except Exception as e:
            self.app.call_from_thread(log_view.write, f"Error streaming logs: {e}")

    def on_key(self, event) -> None:
        if event.key == "escape": self.app.pop_screen()

class NewTunnelModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_container"):
            yield Label("🚀 Open New Tunnel", id="confirm_title")
            yield Label("Enter local port to expose:", id="confirm_text")
            yield Input(placeholder="e.g. 8080", id="port_input")
            with Horizontal(id="confirm_buttons"):
                yield Static("[bold green][ENTER][/] Open", id="btn_yes")
                yield Static("[bold red][ESC][/] Cancel", id="btn_no")

    def on_mount(self) -> None:
        self.query_one("#port_input").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        port = event.value.strip()
        if port.isdigit():
            self.app.pop_screen()
            def _open_tunnel():
                try:
                    subprocess.run(["fire", "tunnel", "open", port], capture_output=True)
                    self.app.call_from_thread(self.app.notify, f"Tunnel opened for port {port}")
                except Exception as e:
                    self.app.call_from_thread(self.app.notify, f"Tunnel error: {e}", severity="error")
            self.app.run_worker(_open_tunnel, thread=True)
        else:
            self.notify("Invalid port", severity="error")

    def on_key(self, event) -> None:
        if event.key == "escape": self.app.pop_screen()

class TunnelModal(ModalScreen):
    BINDINGS = [
        Binding("n", "new_tunnel", "New Tunnel", show=True),
        Binding("d", "delete_tunnel", "Close Tunnel", show=True),
        Binding("escape", "close", "Close", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="tunnel_container"):
            yield Label("🔥 Active Fire Tunnels 🔥", id="tunnel_title")
            yield DataTable(id="tunnel_table")
            yield Label("Press [bold white]N[/] New | [bold white]D[/] Close | [bold white]ESC[/] Exit", id="tunnel_footer")

    def action_close(self) -> None: self.app.pop_screen()

    def action_new_tunnel(self) -> None:
        self.app.push_screen(NewTunnelModal(), callback=lambda _: self.update_tunnels())

    def action_delete_tunnel(self) -> None:
        table = self.query_one("#tunnel_table", DataTable)
        if table.cursor_row is not None:
            port = table.get_row_at(table.cursor_row)[0].replace("[bold yellow]", "").replace("[/]", "")
            subprocess.run(["fire", "tunnel", "close", port], capture_output=True)
            self.notify(f"Closed tunnel on port {port}")
            self.update_tunnels()

    def on_mount(self) -> None:
        table = self.query_one("#tunnel_table", DataTable)
        table.add_columns("Port", "Provider", "Age", "Status", "URL")
        table.cursor_type = "row"
        self.update_tunnels()
        self.set_interval(3.0, self.update_tunnels)

    def update_tunnels(self) -> None:
        table = self.query_one("#tunnel_table", DataTable)
        table.clear()
        files = sorted([os.path.join(TUNNEL_DIR, f) for f in os.listdir(TUNNEL_DIR) if f.endswith(".env")]) if os.path.isdir(TUNNEL_DIR) else []
        if not files: return
        now = time.time()
        for f in sorted(files):
            try:
                with open(f, 'r') as file:
                    content = file.read()
                    port = re.search(r"PORT=(\d+)", content)
                    url = re.search(r"URL=(https://[^\s]+)", content)
                    start_ts = re.search(r"START_TS=(\d+)", content)
                    provider = re.search(r"PROVIDER=([^\s]+)", content)
                    if port:
                        p_val = port.group(1)
                        url_val = f"[cyan]{url.group(1)}[/]" if url else "[dim]pending...[/]"
                        prov_val = f"[white]{provider.group(1)}[/]" if provider else "[white]quick[/]"
                        age = "-"
                        if start_ts:
                            diff = int(now - int(start_ts.group(1)))
                            if diff < 60: age = f"{diff}s"
                            elif diff < 3600: age = f"{diff//60}m"
                            else: age = f"{diff//3600}h"
                        status = "[bold green]ONLINE[/]" if url else "[bold yellow]PENDING[/]"
                        table.add_row(f"[bold yellow]{p_val}[/]", prov_val, age, status, url_val)
            except Exception as e: _log.debug("Error reading tunnel file %s: %s", f, e)

class FireTUI(App):
    CSS = """
    Screen { background: #0a0a0a; }
    #logo { height: 9; content-align: center middle; margin: 1 0; color: #ff5555; }
    DataTable { height: 1fr; margin: 0 2; border: tall #333333; background: #0a0a0a; }
    DataTable > .datatable--header { background: #1a1a1a; color: #ffaa00; text-style: bold; }
    DataTable > .datatable--header-cell { padding: 1 2; }
    DataTable > .datatable--row { height: 2; }
    DataTable > .datatable--cursor { background: #ff4400 30%; color: #ffffff; }
    #info_bar { height: 4; padding: 0 2; background: #111111; color: #cccccc; border-top: solid #ff4400; content-align: center middle; }
    #search_container { display: none; height: 3; margin: 0 2; background: #1a1a1a; border: solid #ffaa00; }
    #search_input { background: transparent; border: none; color: #ffffff; width: 100%; }
    #search_icon { color: #ffaa00; padding: 0 1; }
    Footer { background: #000000; color: #888888; }
    ModalScreen { align: center middle; }
    #log_container, #tunnel_container, #confirm_container, #config_container { width: 90%; height: 80%; background: #0f0f0f; border: thick #ff4400; }
    #confirm_container { height: auto; min-height: 40%; max-height: 70%; width: 60%; }
    #log_title, #tunnel_title, #confirm_title, #config_title { text-align: center; background: #1a1a1a; color: #ffaa00; text-style: bold; padding: 1; border-bottom: solid #ff4400; }
    #log_view, #confirm_list, #config_edit { height: 1fr; background: #000000; color: #00ff00; padding: 1; }
    #confirm_text, #confirm_text_mem, #confirm_text_cpu { padding: 1 2; color: #ffffff; }
    #confirm_buttons { height: 3; align: center middle; background: #1a1a1a; }
    #btn_yes, #btn_no { padding: 0 3; margin: 0 2; }
    #tunnel_table { height: 1fr; background: #000000; margin: 1 2; border: none; }
    #tunnel_table > .datatable--header { background: #1a1a1a; color: #ffaa00; text-style: bold; }
    #tunnel_table > .datatable--cursor { background: #ff4400 30%; color: #ffffff; }
    #log_footer, #tunnel_footer, #config_footer { text-align: center; color: #888888; padding: 1; background: #111111; border-top: solid #333333; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "restart_process", "Restart", show=True),
        Binding("s", "toggle_process", "Stop/Start", show=True),
        Binding("w", "toggle_watchdog", "Watch", show=True),
        Binding("h", "toggle_reload", "Reload", show=True),
        Binding("e", "edit_config", "Edit", show=True),
        Binding("o", "open_script", "Open Script", show=True),
        Binding("m", "limit_resources", "Limits", show=True),
        Binding("c", "clear_logs", "Clear Logs", show=True),
        Binding("i", "show_info", "Info", show=True),
        Binding("v", "live_view", "Live Cockpit", show=True),
        Binding("d", "delete_process", "Delete", show=True),
        Binding("f5", "refresh_data", "Refresh", show=True),
        Binding("slash", "toggle_search", "Search", show=True),
        Binding("space", "toggle_select", "Select", show=True),
        Binding("l", "show_logs", "Logs", show=True),
        Binding("t", "show_tunnels", "Tunnels", show=True),
        Binding("f", "toggle_full_screen", "Full Screen", show=False),
    ]

    LOGO = """[#ff5555]    ▄████████  [#ff0000]▄█  [#ff8800]███▄▄▄▄      [#ffff00]▄████████ 
[#ff5555]   ███    ███ [#ff0000]███  [#ff8800]███▀▀▀██▄   [#ffff00]███    ███ 
[#ff5555]   ███    █▀  [#ff0000]███▌ [#ff8800]███   ███   [#ffff00]███    █▀  
[#ff5555]  ▄███▄▄▄     [#ff0000]███▌ [#ff8800]███   ███  [#ffff00]▄███▄▄▄     
[#ff5555] ▀▀███▀▀▀     [#ff0000]███▌ [#ff8800]███   ███ [#ffff00]▀▀███▀▀▀     
[#ff5555]   ███        [#ff0000]███  [#ff8800]███   ███   [#ffff00]███    █▄  
[#ff5555]   ███        [#ff0000]███  [#ff8800]███   ███   [#ffff00]███    ███ 
[#ff5555]   ███        [#ff0000]█▀    [#ff8800]▀█   █▀    [#ffff00]████████▀  [/]
[#00ffff][b]Fire Process Manager[/] - Interactive Mode"""

    def compose(self) -> ComposeResult:
        yield Static(self.LOGO, id="logo")
        with Horizontal(id="search_container"):
            yield Label(" 🔍 ", id="search_icon")
            yield Input(placeholder="Search processes...", id="search_input")
        table = DataTable(cursor_type="row")
        table.header_height = 3
        table.row_height = 2
        yield table
        yield Static(id="info_bar")
        yield Footer()

    def on_mount(self) -> None:
        self.selected_apps = set()
        self.app_to_svc = {}
        self.filter_text = ""
        self.known_rows = {}
        table = self.query_one(DataTable)
        self.cols = ["ID", "App Name", "Status", "Watch", "Reload", "Port", "Uptime", "Rest", "Mem", "MemLim", "CPU", "CPULim", "PID"]
        for col in self.cols: table.add_column(col, key=col)
        self.sort_column = "App Name"
        self.sort_desc = False
        self.update_data()
        self.set_interval(3.0, self.update_data)
        table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input":
            if self.query_one("#search_container").styles.display != "none":
                self.filter_text = event.value.lower()
                self.update_data()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            self.query_one(DataTable).focus()
            self.action_toggle_search()

    def action_toggle_search(self) -> None:
        search_container = self.query_one("#search_container")
        search_input = self.query_one("#search_input")
        if search_container.styles.display == "none":
            search_container.styles.display = "block"
            search_input.focus()
        else:
            search_container.styles.display = "none"
            self.filter_text = ""
            search_input.value = ""
            self.query_one(DataTable).focus()
            self.update_data()

    def action_toggle_select(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            if name in self.selected_apps: self.selected_apps.remove(name)
            else: self.selected_apps.add(name)
            self.update_data()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column_label = event.column_key.value
        if not column_label: return
        if self.sort_column == column_label: self.sort_desc = not self.sort_desc
        else: self.sort_column = column_label; self.sort_desc = False
        self.notify(f"Sorting by {column_label}")
        self.update_data()

    def update_data(self) -> None:
        """Trigger a non-blocking background data refresh."""
        self._refresh_data_worker()

    @work(exclusive=True, thread=True)
    def _refresh_data_worker(self) -> None:
        """Collect data in background thread, then update UI on main thread."""
        try:
            data = self._collect_data()
            self.app.call_from_thread(self._apply_data, data)
        except Exception as e:
            _log.warning("Error in refresh worker: %s", e)

    def _collect_data(self):
        """Collect data via fire CLI — runs in worker thread."""
        try:
            raw = subprocess.check_output(
                ["fire", "list", "--json"],
                universal_newlines=True, timeout=10
            )
            data = json.loads(raw)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            _log.warning("Error collecting data: %s", e)
            return None

        procs = data.get("processes", [])
        if not procs:
            return None

        filter_text = self.filter_text
        selected_apps = set(self.selected_apps)
        sort_column = self.sort_column
        sort_desc = self.sort_desc

        rows = []
        app_to_svc = {}
        total_mem_bytes = 0
        online = 0

        for p in procs:
            name = p.get("name", "unknown")
            if filter_text and filter_text not in name.lower():
                continue

            status = p.get("status", "stopped")
            svc_key = f"{PREFIX}{name}.service"
            app_to_svc[name] = svc_key

            mem_str = p.get("mem", "0.0MB")
            try:
                mem_bytes = int(float(mem_str.replace("MB", "")) * 1024 * 1024)
            except (ValueError, AttributeError):
                mem_bytes = 0
            total_mem_bytes += mem_bytes

            cpu_str = p.get("cpu", "0.0%")
            try:
                cpu_val = float(cpu_str.replace("%", ""))
            except (ValueError, AttributeError):
                cpu_val = 0.0

            if status == "online":
                online += 1

            pid_val = p.get("pid")
            pid_str = str(pid_val) if pid_val and pid_val > 0 else "-"

            status_disp = "[#00ff00]● online[/]" if status == "online" else f"[#ff0000]○ {status}[/]"

            watch = p.get("watch", "no")
            watch_disp = "[bold green]YES[/]" if watch not in ("no", "") else "[dim]NO[/]"

            reload_status = p.get("reload", "off")
            if reload_status == "active":
                reload_disp = "[bold green]HOT[/]"
            elif reload_status == "ready":
                reload_disp = "[yellow]READY[/]"
            else:
                reload_disp = "[dim]OFF[/]"

            mem_lim = p.get("mem_limit", "-")
            cpu_lim = p.get("cpu_limit", "-")
            port = p.get("port", "-")

            name_disp = f"[#ffaa00]▶[/] {name}" if name in selected_apps else name

            rows.append({
                "App Name": name_disp, "_raw_name": name, "Status": status_disp, "_status_raw": status,
                "Watch": watch_disp, "_watch_raw": watch,
                "Reload": reload_disp,
                "Port": port, "Uptime": p.get("uptime", "-"),
                "Rest": str(p.get("restarts", 0)),
                "Mem": mem_str, "MemLim": mem_lim,
                "CPU": cpu_str, "CPULim": cpu_lim,
                "PID": pid_str,
                "_mem_bytes": mem_bytes, "_cpu_val": cpu_val, "_svc": svc_key
            })

        sort_key_map = {
            "App Name": lambda x: x["_raw_name"].lower(), "Status": lambda x: x["_status_raw"],
            "Watch": lambda x: x["_watch_raw"],
            "Port": lambda x: x["Port"], "Uptime": lambda x: x["Uptime"],
            "Rest": lambda x: int(x["Rest"]),
            "Mem": lambda x: x["_mem_bytes"], "MemLim": lambda x: x["MemLim"],
            "CPU": lambda x: x["_cpu_val"], "CPULim": lambda x: x["CPULim"],
            "PID": lambda x: int(x["PID"]) if x["PID"] != "-" else -1
        }
        rows.sort(key=sort_key_map.get(sort_column, lambda x: x["_raw_name"]), reverse=sort_desc)
        for i, r in enumerate(rows):
            r["ID"] = str(i)

        tunnels = len([f for f in os.listdir(TUNNEL_DIR) if f.endswith(".env")]) if os.path.isdir(TUNNEL_DIR) else 0

        return {
            "rows": rows,
            "app_to_svc": app_to_svc,
            "total_mem": total_mem_bytes,
            "online": online,
            "tunnels": tunnels,
            "sort_column": sort_column,
            "sort_desc": sort_desc,
        }

    def _apply_data(self, data) -> None:
        """Fast UI update — runs on main thread, no subprocess calls."""
        if data is None:
            table = self.query_one(DataTable)
            table.clear()
            self.known_rows = {}
            return

        self.app_to_svc.update(data["app_to_svc"])
        rows = data["rows"]
        table = self.query_one(DataTable)

        # Preserve cursor position
        current_row_key = None
        if table.cursor_row is not None:
            row_keys = list(table.rows.keys())
            if table.cursor_row < len(row_keys):
                current_row_key = row_keys[table.cursor_row]

        visible_svcs = [r["_svc"] for r in rows]
        current_keys = list(table.rows.keys())

        # If order or set of services changed, refresh entire table
        if current_keys != visible_svcs:
            table.clear()
            self.known_rows = {}
            for r in rows:
                svc_key, display_data = r["_svc"], [r[col] for col in self.cols]
                table.add_row(*display_data, key=svc_key)
                self.known_rows[svc_key] = display_data
            
            if current_row_key is not None and current_row_key in visible_svcs:
                try:
                    new_index = visible_svcs.index(current_row_key)
                    table.move_cursor(row=new_index)
                except (ValueError, KeyError, IndexError): pass
        else:
            # Just update cells for existing rows
            for r in rows:
                svc_key, display_data = r["_svc"], [r[col] for col in self.cols]
                old_data = self.known_rows.get(svc_key)
                if old_data:
                    for i, col_name in enumerate(self.cols):
                        if display_data[i] != old_data[i]:
                            table.update_cell(svc_key, col_name, display_data[i])
                    self.known_rows[svc_key] = display_data

        info_bar = self.query_one("#info_bar", Static)
        info_bar.update(f"Total: [bold yellow]{len(rows)}[/]  Online: [bold green]{data['online']}[/]  Memory: [bold cyan]{data['total_mem']/(1024*1024):.1f}MB[/]  Tunnels: [bold yellow]{data['tunnels']}[/]\n[grey]Sorted by: [white]{data['sort_column']}[/] {'▼' if data['sort_desc'] else '▲'}  |  Selected: [white]{len(self.selected_apps)}[/][/]")

    def get_targets(self):
        if self.selected_apps: return list(self.selected_apps)
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            raw_name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            return [raw_name]
        return []

    def action_restart_process(self) -> None:
        targets = self.get_targets()
        if not targets: return
        
        # Resolve names before entering thread
        svc_names = []
        for name in targets:
            svc = self.app_to_svc.get(name)
            if svc: svc_names.append(svc)

        def do_restart():
            try:
                for svc in svc_names:
                    subprocess.run(["systemctl", "restart", svc], capture_output=True)
                
                def finish():
                    self.selected_apps.clear()
                    self.update_data()
                    self.notify(f"Restarted {len(svc_names)} processes")
                self.app.call_from_thread(finish)
            except Exception as e:
                self.app.call_from_thread(self.notify, f"Restart error: {e}", severity="error")
        
        self.push_screen(ConfirmationModal("Restart", targets, lambda: self.run_worker(do_restart, thread=True)))

    def action_toggle_process(self) -> None:
        targets = self.get_targets()
        if not targets: return

        # Batch-check current states before entering thread
        targets_data = []
        svcs_for_targets = [(name, self.app_to_svc.get(name)) for name in targets if self.app_to_svc.get(name)]
        if svcs_for_targets:
            try:
                svc_list = [svc for _, svc in svcs_for_targets]
                props = subprocess.check_output(
                    ["systemctl", "show", "--property=ActiveState"] + svc_list,
                    universal_newlines=True
                )
                states = [line.split("=", 1)[1] for line in props.splitlines() if line.startswith("ActiveState=")]
                for i, (name, svc) in enumerate(svcs_for_targets):
                    if i < len(states):
                        targets_data.append((svc, states[i] == "active"))
            except Exception as e:
                _log.warning("Error checking process states: %s", e)

        def do_toggle():
            try:
                for svc, is_active in targets_data:
                    action = "stop" if is_active else "start"
                    subprocess.run(["systemctl", action, svc], capture_output=True)
                
                def finish():
                    self.selected_apps.clear()
                    self.update_data()
                    self.notify(f"Toggled {len(targets_data)} processes")
                self.app.call_from_thread(finish)
            except Exception as e:
                self.app.call_from_thread(self.notify, f"Toggle error: {e}", severity="error")
        
        self.push_screen(ConfirmationModal("Stop/Start", targets, lambda: self.run_worker(do_toggle, thread=True)))

    def action_toggle_watchdog(self) -> None:
        targets = self.get_targets()
        if not targets: return
        def do_watchdog():
            for name in targets:
                svc_name = self.app_to_svc.get(name)
                if not svc_name: continue
                svc_file = f"/etc/systemd/system/{svc_name}"
                try:
                    with open(svc_file, "r") as f: content = f.read()
                    if "Restart=always" in content: content = content.replace("Restart=always", "Restart=no")
                    else: content = content.replace("Restart=no", "Restart=always")
                    with open(svc_file, "w") as f: f.write(content)
                    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                except Exception as e: self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.app.call_from_thread(self.update_data)
            self.app.call_from_thread(self.notify, f"Watchdog toggled for {len(targets)} processes")
        
        self.push_screen(ConfirmationModal("Toggle Watchdog", targets, lambda: self.run_worker(do_watchdog, thread=True)))

    def action_toggle_reload(self) -> None:
        targets = self.get_targets()
        if not targets: return
        def do_reload():
            for name in targets:
                svc_name = self.app_to_svc.get(name)
                if not svc_name: continue
                path_name = svc_name.replace(".service", ".path")
                path_file = f"/etc/systemd/system/{path_name}"
                
                if os.path.exists(path_file):
                    subprocess.run(["systemctl", "stop", path_name], capture_output=True)
                    subprocess.run(["systemctl", "disable", path_name], capture_output=True)
                    os.remove(path_file)
                    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                    self.app.call_from_thread(self.notify, f"Auto-reload disabled for {name}")
                else:
                    try:
                        out = subprocess.check_output(["systemctl", "show", svc_name, "--property=ExecStart", "--property=WorkingDirectory"], universal_newlines=True)
                        work_dir, script_path = "", ""
                        for line in out.splitlines():
                            if line.startswith("WorkingDirectory="): work_dir = line.split("=", 1)[1]
                            elif line.startswith("ExecStart="):
                                match = re.search(r"argv\[\]=([^;]+)", line)
                                if match:
                                    argv = match.group(1).split()
                                    if len(argv) > 1: script_path = argv[1]
                        
                        if not script_path or not os.path.isabs(script_path):
                            if script_path and work_dir: script_path = os.path.join(work_dir, script_path)
                        
                        if script_path and os.path.exists(script_path):
                            with open(path_file, "w") as f:
                                f.write(f"[Unit]\nDescription=Watch {script_path} for {name}\n\n[Path]\nPathModified={script_path}\nUnit=fire-reload@{svc_name}.service\n\n[Install]\nWantedBy=multi-user.target\n")
                            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                            subprocess.run(["systemctl", "enable", "--now", path_name], capture_output=True)
                            self.app.call_from_thread(self.notify, f"Auto-reload enabled for {name}")
                        else:
                            self.app.call_from_thread(self.notify, f"Could not find script for {name}", severity="error")
                    except Exception as e:
                        self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.app.call_from_thread(self.update_data)
        
        self.run_worker(do_reload, thread=True)

    def action_edit_config(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            app_name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            svc_name = self.app_to_svc.get(app_name)
            if svc_name: self.push_screen(ConfigEditorModal(svc_name, app_name))

    def action_open_script(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            app_name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            svc_name = self.app_to_svc.get(app_name)
            if not svc_name: return
            
            try:
                out = subprocess.check_output(["systemctl", "show", svc_name, "--property=ExecStart", "--property=WorkingDirectory"], universal_newlines=True)
                work_dir, script_path = "", ""
                for line in out.splitlines():
                    if line.startswith("WorkingDirectory="): work_dir = line.split("=", 1)[1]
                    elif line.startswith("ExecStart="):
                        match = re.search(r"argv\[\]=([^;]+)", line)
                        if match:
                            argv = match.group(1).split()
                            if len(argv) > 1: script_path = argv[1]
                
                if not script_path or not os.path.isabs(script_path):
                    if script_path and work_dir: script_path = os.path.join(work_dir, script_path)
                
                if script_path and os.path.exists(script_path):
                    self.exit_with_command(f"nano {script_path}")
                else:
                    self.notify(f"Could not find script file for {app_name}", severity="error")
            except Exception as e:
                self.notify(f"Error finding script: {e}", severity="error")

    def action_limit_resources(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            app_name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            svc_name = self.app_to_svc.get(app_name)
            if svc_name: self.push_screen(ResourceLimitsModal(svc_name, app_name))

    def action_clear_logs(self) -> None:
        def do_clear():
            try:
                subprocess.run(["journalctl", "--rotate"], check=True, capture_output=True)
                subprocess.run(["journalctl", "--vacuum-time=1s"], check=True, capture_output=True)
                self.app.call_from_thread(self.notify, "System journal logs have been purged")
            except Exception as e:
                self.app.call_from_thread(self.notify, f"Error purging logs: {e}", severity="error")
        
        self.push_screen(ConfirmationModal("Purge Logs", ["All System Journal Logs"], lambda: self.run_worker(do_clear, thread=True)))

    def action_show_logs(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None:
            app_name = table.get_row_at(table.cursor_row)[1].replace("[#ffaa00]▶[/] ", "")
            svc_name = self.app_to_svc.get(app_name)
            if svc_name: self.push_screen(LogModal(svc_name, app_name))
            else: self.notify(f"No log source for {app_name}", severity="error")

    def action_show_tunnels(self) -> None: self.push_screen(TunnelModal())

    def action_show_info(self) -> None:
        targets = self.get_targets()
        if targets: self.exit_with_command(f"fire info {targets[0]}")

    def action_live_view(self) -> None:
        targets = self.get_targets()
        if targets: self.exit_with_command(f"fire live {targets[0]}")

    def action_delete_process(self) -> None:
        targets = self.get_targets()
        if not targets: return
        def do_delete():
            for name in targets: subprocess.run(["fire", "delete", name], capture_output=True)
            self.app.call_from_thread(self.selected_apps.clear)
            self.app.call_from_thread(self.update_data)
            self.app.call_from_thread(self.notify, f"Deleted {len(targets)} processes")
        
        self.push_screen(ConfirmationModal("Delete", targets, lambda: self.run_worker(do_delete, thread=True)))

    def action_toggle_full_screen(self) -> None:
        logo = self.query_one("#logo")
        logo.display = not logo.display

    def action_refresh_data(self) -> None: self.update_data()
    def exit_with_command(self, cmd):
        with open("/tmp/fire_tui_next_cmd", "w") as f: f.write(cmd)
        self.exit()

if __name__ == "__main__": app = FireTUI(); app.run()
