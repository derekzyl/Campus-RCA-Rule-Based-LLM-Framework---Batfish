"""Tkinter UI for Campus RCA — setup, diagnose, evaluate, browse results."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable, Optional

from campus_rca import config as config_mod
from campus_rca.config import ROOT, Settings
from campus_rca.pipeline import RCAPipeline, load_scenarios
from campus_rca.setup_checks import (
    gather_setup_report,
    ensure_project_synced,
    list_ollama_models,
    model_is_local,
    pull_ollama_model,
    resolve_local_model_name,
    set_env_ollama_model,
    start_ollama_serve,
)


MODES = ("hybrid", "rule_only", "llm_only")
BACKENDS = ("ollama", "openai")


class CampusRCAGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Campus RCA — Batfish + Rules + LLM")
        self.geometry("980x740")
        self.minsize(860, 620)

        self._busy = False
        self._task_started = 0.0
        self._timer_after: Optional[str] = None
        self._action_buttons: list[ttk.Button] = []
        self._scenarios: list[dict[str, Any]] = []
        self._last_result: Optional[dict[str, Any]] = None

        self._build()
        self.after(200, self.refresh_setup)
        self.after(400, self.reload_scenarios)
        self.after(700, self.refresh_local_models)
        self.after(1200, self._prompt_model_on_startup)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        header = ttk.Frame(self, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Campus Network Root Cause Analysis",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Deterministic Batfish/rules evidence + local Ollama explanations (masters prototype)",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        # Always-visible activity banner
        activity = ttk.LabelFrame(self, text="Activity", padding=(10, 6))
        activity.pack(fill="x", padx=10, pady=(0, 6))
        self.activity_var = tk.StringVar(value="Idle — click a button to begin.")
        self.elapsed_var = tk.StringVar(value="")
        top_act = ttk.Frame(activity)
        top_act.pack(fill="x")
        self.activity_lbl = ttk.Label(
            top_act,
            textvariable=self.activity_var,
            font=("Segoe UI", 10, "bold"),
            foreground="#0b3d5c",
        )
        self.activity_lbl.pack(side="left", anchor="w")
        ttk.Label(top_act, textvariable=self.elapsed_var).pack(side="right")
        self.progress = ttk.Progressbar(activity, mode="indeterminate", length=400)
        self.progress.pack(fill="x", pady=(6, 2))
        self.phase_var = tk.StringVar(value="")
        ttk.Label(activity, textvariable=self.phase_var, wraplength=920).pack(anchor="w")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tab_setup = ttk.Frame(self.notebook, padding=10)
        self.tab_diag = ttk.Frame(self.notebook, padding=10)
        self.tab_eval = ttk.Frame(self.notebook, padding=10)
        self.tab_results = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_setup, text="1. Setup")
        self.notebook.add(self.tab_diag, text="2. Diagnose")
        self.notebook.add(self.tab_eval, text="3. Evaluate")
        self.notebook.add(self.tab_results, text="4. Results")

        self._build_setup()
        self._build_diagnose()
        self._build_eval()
        self._build_results()

        status = ttk.Frame(self, padding=(12, 4))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.busy_badge = ttk.Label(status, text="READY", font=("Segoe UI", 9, "bold"))
        self.busy_badge.pack(side="right")

    def _btn(self, parent, text: str, command, **pack_kw) -> ttk.Button:
        b = ttk.Button(parent, text=text, command=command)
        b.pack(**pack_kw)
        self._action_buttons.append(b)
        return b

    def _build_setup(self) -> None:
        top = ttk.Frame(self.tab_setup)
        top.pack(fill="x")
        self._btn(top, "Re-check system", self.refresh_setup, side="left", padx=(0, 6))
        self._btn(top, "uv sync", self.do_uv_sync, side="left", padx=6)
        self._btn(top, "Start Ollama", self.do_start_ollama, side="left", padx=6)
        self._btn(top, "Choose Ollama model…", self.choose_ollama_model, side="left", padx=6)
        self._btn(top, "Start Batfish", self.do_start_batfish, side="left", padx=6)

        self.platform_var = tk.StringVar(value="")
        ttk.Label(
            self.tab_setup, textvariable=self.platform_var, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(10, 4))

        cols = ("name", "ok", "detail", "fix")
        self.setup_tree = ttk.Treeview(
            self.tab_setup, columns=cols, show="headings", height=10
        )
        for c, w in zip(cols, (110, 50, 420, 280)):
            self.setup_tree.heading(c, text=c.upper())
            self.setup_tree.column(c, width=w, anchor="w")
        self.setup_tree.pack(fill="both", expand=True, pady=6)

        self.setup_log = scrolledtext.ScrolledText(self.tab_setup, height=8, wrap="word")
        self.setup_log.pack(fill="both", expand=True)

    def _build_diagnose(self) -> None:
        form = ttk.LabelFrame(self.tab_diag, text="Diagnosis settings", padding=10)
        form.pack(fill="x")

        self.scenario_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="hybrid")
        self.backend_var = tk.StringVar(value="ollama")
        self.offline_var = tk.BooleanVar(value=False)
        self.model_var = tk.StringVar(value=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"))

        row = 0
        ttk.Label(form, text="Scenario").grid(row=row, column=0, sticky="w")
        self.scenario_box = ttk.Combobox(
            form, textvariable=self.scenario_var, state="readonly", width=48
        )
        self.scenario_box.grid(row=row, column=1, sticky="we", padx=6, pady=3)

        row += 1
        ttk.Label(form, text="Mode").grid(row=row, column=0, sticky="w")
        ttk.Combobox(
            form, textvariable=self.mode_var, values=MODES, state="readonly", width=20
        ).grid(row=row, column=1, sticky="w", padx=6, pady=3)

        row += 1
        ttk.Label(form, text="LLM backend").grid(row=row, column=0, sticky="w")
        ttk.Combobox(
            form, textvariable=self.backend_var, values=BACKENDS, state="readonly", width=20
        ).grid(row=row, column=1, sticky="w", padx=6, pady=3)

        row += 1
        ttk.Label(form, text="Ollama model").grid(row=row, column=0, sticky="w")
        model_row = ttk.Frame(form)
        model_row.grid(row=row, column=1, sticky="w", padx=6, pady=3)
        self.model_box = ttk.Combobox(
            model_row, textvariable=self.model_var, width=28, state="readonly"
        )
        self.model_box.pack(side="left")
        ttk.Button(model_row, text="Refresh", command=self.refresh_local_models).pack(
            side="left", padx=6
        )
        ttk.Button(model_row, text="Choose…", command=self.choose_ollama_model).pack(
            side="left"
        )

        row += 1
        ttk.Checkbutton(
            form,
            text="Offline evidence (no live Batfish — use cache/synthetic)",
            variable=self.offline_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)

        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(self.tab_diag)
        btns.pack(fill="x", pady=8)
        self._btn(btns, "Run diagnosis", self.run_diagnose, side="left", padx=(0, 6))
        self._btn(btns, "Save JSON…", self.save_last_result, side="left")

        self.symptom_lbl = ttk.Label(self.tab_diag, text="", wraplength=900, justify="left")
        self.symptom_lbl.pack(anchor="w", pady=(0, 6))

        self.diag_out = scrolledtext.ScrolledText(self.tab_diag, wrap="word")
        self.diag_out.pack(fill="both", expand=True)
        self.scenario_box.bind("<<ComboboxSelected>>", lambda _e: self._show_symptom())

    def _build_eval(self) -> None:
        info = ttk.Label(
            self.tab_eval,
            text=(
                "Runs rule_only, llm_only, and hybrid on all labelled campus scenarios.\n"
                "Uses Ollama by default (real LLM). This can take many minutes on CPU."
            ),
            justify="left",
        )
        info.pack(anchor="w", pady=(0, 8))

        opts = ttk.Frame(self.tab_eval)
        opts.pack(fill="x")
        self.eval_offline = tk.BooleanVar(value=False)
        self.eval_backend = tk.StringVar(value="ollama")
        ttk.Checkbutton(opts, text="Offline evidence", variable=self.eval_offline).pack(
            side="left", padx=(0, 12)
        )
        ttk.Label(opts, text="Backend").pack(side="left")
        ttk.Combobox(
            opts,
            textvariable=self.eval_backend,
            values=BACKENDS,
            state="readonly",
            width=12,
        ).pack(side="left", padx=6)

        self._btn(
            self.tab_eval, "Run full evaluation", self.run_eval, anchor="w", pady=8
        )
        self.eval_out = scrolledtext.ScrolledText(self.tab_eval, wrap="word")
        self.eval_out.pack(fill="both", expand=True)

    def _build_results(self) -> None:
        top = ttk.Frame(self.tab_results)
        top.pack(fill="x")
        self._btn(top, "Refresh list", self.refresh_results, side="left", padx=(0, 6))
        self._btn(top, "Open selected", self.open_selected_result, side="left", padx=(0, 6))
        self._btn(top, "Generate figures", self.generate_figures, side="left", padx=(0, 6))
        self._btn(top, "Open figures folder", self.open_figures_folder, side="left")
        ttk.Label(
            self.tab_results,
            text=(
                "Select an evaluation_report.json then click Generate figures "
                "(CSV + LaTeX tables + PNG charts for Chapter 5)."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(6, 0))

        self.results_list = tk.Listbox(self.tab_results, height=8)
        self.results_list.pack(fill="x", pady=6)
        self.results_view = scrolledtext.ScrolledText(self.tab_results, wrap="word")
        self.results_view.pack(fill="both", expand=True)
        self.refresh_results()

    # -------------------------------------------------------------- helpers
    def log_setup(self, msg: str) -> None:
        self.setup_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.setup_log.see("end")

    def set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def report(self, phase: str, *, log: bool = False) -> None:
        """Update activity banner + optional setup log (thread-safe via after)."""

        def _apply():
            self.phase_var.set(phase)
            self.activity_var.set(f"Working: {phase}" if self._busy else phase)
            if log:
                self.log_setup(phase)

        if threading.current_thread() is threading.main_thread():
            _apply()
        else:
            self.after(0, _apply)

    def _tick_elapsed(self) -> None:
        if not self._busy:
            return
        secs = int(time.time() - self._task_started)
        mins, rem = divmod(secs, 60)
        self.elapsed_var.set(f"Elapsed {mins:02d}:{rem:02d}")
        self._timer_after = self.after(1000, self._tick_elapsed)

    def set_busy(self, busy: bool, task: str = "") -> None:
        self._busy = busy
        if self._timer_after:
            try:
                self.after_cancel(self._timer_after)
            except Exception:  # noqa: BLE001
                pass
            self._timer_after = None

        state = "disabled" if busy else "normal"
        for b in self._action_buttons:
            try:
                b.configure(state=state)
            except tk.TclError:
                pass

        if busy:
            self._task_started = time.time()
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
            self.busy_badge.configure(text="BUSY")
            self.activity_var.set(task or "Working…")
            self.phase_var.set("Started — please wait. Long LLM steps can take several minutes.")
            self.elapsed_var.set("Elapsed 00:00")
            self.configure(cursor="watch")
            self.title("Campus RCA — Working…")
            self._tick_elapsed()
        else:
            self.progress.stop()
            self.progress["value"] = 0
            self.busy_badge.configure(text="READY")
            self.configure(cursor="")
            self.title("Campus RCA — Batfish + Rules + LLM")
            if not task:
                self.activity_var.set("Idle — click a button to begin.")
                self.phase_var.set("")
            self.elapsed_var.set("")

    def set_progress_fraction(self, done: int, total: int, label: str = "") -> None:
        def _apply():
            if total <= 0:
                return
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=total, value=done)
            pct = int(100 * done / total)
            msg = label or f"Progress {done}/{total} ({pct}%)"
            self.phase_var.set(msg)
            self.activity_var.set(f"Working: {msg}")

        self.after(0, _apply)

    def _settings(self, backend: str, offline: bool, model: str) -> Settings:
        config_mod.get_settings.cache_clear()
        base = Settings()
        updates: dict[str, Any] = {
            "llm_backend": backend,  # type: ignore[dict-item]
            "use_batfish": not offline,
            "ollama_model": model,
        }
        return base.model_copy(update=updates)

    def _worker(
        self,
        fn: Callable[[Callable[[str], None]], Any],
        on_done=None,
        *,
        task: str,
    ) -> None:
        if self._busy:
            messagebox.showinfo("Busy", "A task is already running.\nPlease wait until it finishes.")
            return

        def progress(msg: str) -> None:
            self.report(msg, log=True)

        def run():
            self.after(0, lambda: self.set_busy(True, task=task))
            self.after(0, lambda: self.set_status(task))
            err = None
            result = None
            try:
                result = fn(progress)
            except Exception as exc:  # noqa: BLE001
                err = exc

            def finish():
                self.set_busy(False)
                if err:
                    self.activity_var.set(f"Failed: {err}")
                    self.phase_var.set(str(err))
                    messagebox.showerror("Error", str(err))
                    self.set_status(f"Error: {err}")
                elif on_done:
                    on_done(result)

            self.after(0, finish)

        threading.Thread(target=run, daemon=True).start()

    # --------------------------------------------------------------- setup
    def refresh_setup(self) -> None:
        self.report("Checking system…", log=True)
        report = gather_setup_report()
        self.platform_var.set(f"Platform: {report.os_name} / {report.arch}")
        for i in self.setup_tree.get_children():
            self.setup_tree.delete(i)
        for c in report.checks:
            self.setup_tree.insert(
                "",
                "end",
                values=(c.name, "OK" if c.ok else "FAIL", c.detail, c.fix),
            )
        ready = "READY" if report.ready else "NOT READY — fix FAIL rows"
        self.set_status(f"Setup: {ready}")
        self.activity_var.set(f"Setup check finished — {ready}")
        self.phase_var.set("")
        self.log_setup(f"Checked system — {ready}")
        batfish_ok = any(c.name == "Batfish" and c.ok for c in report.checks)
        if not batfish_ok:
            self.offline_var.set(True)
            self.eval_offline.set(True)

    def do_uv_sync(self) -> None:
        def work(progress):
            progress("Running uv sync (installing dependencies)…")
            return ensure_project_synced()

        def done(res):
            ok, detail = res
            self.log_setup(detail[-1500:] if detail else "")
            self.set_status("uv sync OK" if ok else "uv sync failed")
            self.activity_var.set("uv sync finished" if ok else "uv sync failed")
            self.refresh_setup()
            if not ok:
                messagebox.showerror("uv sync failed", detail[-800:])

        self._worker(work, done, task="uv sync")

    def do_start_ollama(self) -> None:
        def work(progress):
            progress("Starting Ollama server…")
            return start_ollama_serve()

        def done(res):
            ok, detail = res
            self.log_setup(f"Ollama: {detail}")
            self.activity_var.set(f"Ollama: {detail}")
            self.refresh_setup()
            self.refresh_local_models()
            if not ok:
                messagebox.showerror("Ollama", detail)
            else:
                self.choose_ollama_model()

        self._worker(work, done, task="Start Ollama")

    def refresh_local_models(self) -> None:
        models = list_ollama_models()
        current = self.model_var.get().strip()
        if hasattr(self, "model_box"):
            self.model_box["values"] = models
            if models:
                # Prefer current if local; else keep first
                concrete = resolve_local_model_name(current, models)
                if concrete:
                    self.model_var.set(concrete)
                elif current not in models:
                    self.model_var.set(models[0])
            else:
                self.model_box.configure(state="normal")
        self.log_setup(
            f"Local Ollama models: {', '.join(models) if models else '(none)'}"
        )
        return models

    def _prompt_model_on_startup(self) -> None:
        models = list_ollama_models()
        if models:
            self.choose_ollama_model(
                title="Local Ollama models found",
                message=(
                    "These models are already downloaded on this PC.\n"
                    "Choose one to use (no re-download), or pull a different name."
                ),
            )

    def choose_ollama_model(
        self,
        title: str = "Choose Ollama model",
        message: str = (
            "Select a model that is already local (no download),\n"
            "or pull a different model name if needed."
        ),
    ) -> None:
        models = list_ollama_models()
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("480x420")

        ttk.Label(dlg, text=message, justify="left", wraplength=440).pack(
            anchor="w", padx=12, pady=(12, 6)
        )

        if models:
            ttk.Label(
                dlg,
                text="Already downloaded (will NOT re-download):",
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", padx=12)
            lb = tk.Listbox(dlg, height=10)
            lb.pack(fill="both", expand=True, padx=12, pady=6)
            for m in models:
                lb.insert("end", m)
            cur = resolve_local_model_name(self.model_var.get(), models)
            if cur and cur in models:
                lb.selection_set(models.index(cur))
            else:
                lb.selection_set(0)
        else:
            lb = None
            ttk.Label(
                dlg,
                text="No local models found yet. Enter a name to download below.",
                foreground="#a33",
            ).pack(anchor="w", padx=12, pady=6)

        ttk.Label(dlg, text="Or enter a different model name:").pack(anchor="w", padx=12)
        other = tk.StringVar()
        ttk.Entry(dlg, textvariable=other, width=40).pack(anchor="w", padx=12, pady=4)

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=12, pady=12)

        def use_selected():
            if lb is not None and lb.curselection():
                name = lb.get(lb.curselection()[0])
                self._apply_model_choice(name, pull_if_missing=False)
                dlg.destroy()
            elif other.get().strip():
                use_other()
            else:
                messagebox.showwarning("Model", "Select a local model or type a name.", parent=dlg)

        def use_other():
            name = other.get().strip()
            if not name:
                messagebox.showwarning("Model", "Type a model name.", parent=dlg)
                return
            dlg.destroy()
            self._apply_model_choice(name, pull_if_missing=True)

        ttk.Button(btns, text="Use selected local model", command=use_selected).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(btns, text="Use typed name", command=use_other).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")

        dlg.wait_window()

    def _apply_model_choice(self, name: str, *, pull_if_missing: bool) -> None:
        local = list_ollama_models()
        concrete = resolve_local_model_name(name, local)
        if concrete:
            set_env_ollama_model(concrete)
            self.model_var.set(concrete)
            self.refresh_local_models()
            self.log_setup(f"Using already-local model (no download): {concrete}")
            self.activity_var.set(f"Model: {concrete} (local)")
            self.set_status(f"OLLAMA_MODEL={concrete}")
            messagebox.showinfo(
                "Model ready",
                f"Using local model:\n{concrete}\n\nNo download was needed.",
            )
            return

        if not pull_if_missing:
            messagebox.showwarning(
                "Not local",
                f"'{name}' is not downloaded yet.\n"
                "Type it in the dialog and click 'Use typed name' to pull it.",
            )
            return

        def work(progress):
            progress(f"Checking local models for '{name}'…")
            if model_is_local(name):
                resolved = resolve_local_model_name(name) or name
                return True, f"already local — skipped download ({resolved})", resolved
            progress(f"'{name}' not local — downloading once…")
            ok, detail = pull_ollama_model(name, force=False)
            return ok, detail, name

        def done(res):
            ok, detail, resolved = res
            self.log_setup(detail)
            if ok:
                # re-resolve after pull
                concrete2 = resolve_local_model_name(resolved) or resolved
                set_env_ollama_model(concrete2)
                self.model_var.set(concrete2)
                self.refresh_local_models()
                self.activity_var.set(f"Model: {concrete2}")
                self.set_status(f"OLLAMA_MODEL={concrete2}")
                messagebox.showinfo("Model ready", f"{concrete2}\n\n{detail}")
            else:
                messagebox.showerror("Pull failed", detail[-800:])

        self._worker(work, done, task=f"Select/pull model {name}")

    def do_start_batfish(self) -> None:
        def work(progress):
            progress("Starting Batfish via Podman/Docker (image pull can be slow)…")
            script = ROOT / "scripts" / "ensure_batfish.sh"
            import subprocess

            env = os.environ.copy()
            sock = f"/run/user/{os.getuid()}/podman/podman.sock"
            if Path(sock).exists():
                env["DOCKER_HOST"] = f"unix://{sock}"
            p = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                env=env,
                timeout=1800,
            )
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            progress("Batfish start command finished — checking result…")
            return p.returncode == 0, out

        def done(res):
            ok, detail = res
            self.log_setup(detail[-2000:] if detail else "")
            self.refresh_setup()
            if ok:
                self.offline_var.set(False)
                self.eval_offline.set(False)
                self.set_status("Batfish ready")
                self.activity_var.set("Batfish is reachable")
                messagebox.showinfo("Batfish", "Batfish is reachable.")
            else:
                self.offline_var.set(True)
                self.eval_offline.set(True)
                self.set_status("Batfish offline — using cached evidence")
                self.activity_var.set("Batfish unavailable — offline mode")
                messagebox.showwarning(
                    "Batfish unavailable",
                    "Could not start Batfish.\n"
                    "The app still works with Offline evidence checked.\n\n"
                    + (detail[-600:] if detail else ""),
                )

        self._worker(work, done, task="Start Batfish")

    # ------------------------------------------------------------ diagnose
    def reload_scenarios(self) -> None:
        try:
            data = load_scenarios()
            self._scenarios = data.get("scenarios", [])
            ids = [s["id"] for s in self._scenarios]
            self.scenario_box["values"] = ids
            if ids and not self.scenario_var.get():
                self.scenario_var.set(ids[0])
            self._show_symptom()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Scenarios", str(exc))

    def _show_symptom(self) -> None:
        sid = self.scenario_var.get()
        sc = next((s for s in self._scenarios if s["id"] == sid), None)
        if sc:
            self.symptom_lbl.configure(
                text=f"Symptom: {sc.get('symptom', '')}\nGround truth: "
                f"{sc['ground_truth']['fault_type']} @ {sc['ground_truth'].get('device')}"
            )

    def run_diagnose(self) -> None:
        sid = self.scenario_var.get()
        if not sid:
            messagebox.showwarning("Scenario", "Select a scenario first.")
            return
        mode = self.mode_var.get()
        backend = self.backend_var.get()
        offline = self.offline_var.get()
        model = self.model_var.get().strip()

        self.diag_out.delete("1.0", "end")
        self.diag_out.insert(
            "1.0",
            f"Starting diagnosis…\n"
            f"  scenario={sid}\n  mode={mode}\n  backend={backend}\n"
            f"  offline={offline}\n  model={model}\n\n"
            "Please wait — Ollama can take several minutes on CPU.\n",
        )

        def work(progress):
            progress(f"Collecting evidence for {sid}…")
            settings = self._settings(backend, offline, model)
            if settings.llm_backend == "openai" and not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY missing in environment / .env")
            sc = next(s for s in load_scenarios()["scenarios"] if s["id"] == sid)
            pipe = RCAPipeline(settings)
            progress(f"Running {mode} pipeline (rules / LLM as needed)…")
            if mode in {"hybrid", "llm_only"}:
                progress("Calling LLM — keep this window open…")
            result = pipe.run_scenario(sc, mode=mode)
            progress("Saving result JSON…")
            out = ROOT / "results" / f"gui_{sid}_{mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result.model_dump_json(indent=2))
            progress("Diagnosis complete.")
            return result.model_dump(), str(out)

        def done(res):
            payload, path = res
            self._last_result = payload
            self.diag_out.delete("1.0", "end")
            lines = [
                f"Mode: {payload['mode']}",
                f"Scenario: {payload['scenario_id']}",
                f"Fault: {payload['final_fault_type']}  @  {payload['final_device']}",
                f"Elapsed: {payload['elapsed_ms']:.0f} ms",
                f"Evidence source: {payload['evidence'].get('source')}",
                "",
                "Explanation:",
                payload.get("final_explanation") or "",
                "",
                "Remediation (human approval required):",
            ]
            for step in payload.get("remediation") or []:
                lines.append(f"  • {step}")
            if payload.get("llm_diagnosis"):
                halls = payload["llm_diagnosis"].get("hallucinated_claims") or []
                if halls:
                    lines += ["", "Faithfulness flags:"]
                    lines += [f"  • {h}" for h in halls]
            if payload.get("rule_diagnosis") and payload["rule_diagnosis"].get("primary"):
                p = payload["rule_diagnosis"]["primary"]
                lines += [
                    "",
                    "Rule hit:",
                    f"  {p.get('rule_id')}  conf={p.get('confidence')}  {p.get('rationale')}",
                ]
            lines += [
                "",
                f"Saved: {path}",
                "",
                "--- raw JSON ---",
                json.dumps(payload, indent=2)[:8000],
            ]
            self.diag_out.insert("1.0", "\n".join(lines))
            self.set_status(f"Done: {payload['final_fault_type']} @ {payload['final_device']}")
            self.activity_var.set(
                f"Diagnosis done — {payload['final_fault_type']} @ {payload['final_device']}"
            )
            self.phase_var.set(f"Saved to {path}")
            self.refresh_results()
            self.notebook.select(self.tab_diag)

        self._worker(work, done, task=f"Diagnose {sid} ({mode})")

    def save_last_result(self) -> None:
        if not self._last_result:
            messagebox.showinfo("Save", "Run a diagnosis first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="rca_result.json",
        )
        if path:
            Path(path).write_text(json.dumps(self._last_result, indent=2))
            messagebox.showinfo("Saved", path)

    # ---------------------------------------------------------------- eval
    def run_eval(self) -> None:
        backend = self.eval_backend.get()
        offline = self.eval_offline.get()
        self.eval_out.delete("1.0", "end")
        self.eval_out.insert(
            "1.0",
            "Starting full evaluation…\n"
            "This runs every scenario × 3 modes with a real LLM.\n"
            "Live lines will appear below as each case finishes.\n\n",
        )

        def work(progress):
            import sys

            sys.path.insert(0, str(ROOT))
            from evaluation.metrics import score_row, write_report

            progress("Loading scenarios and configuring pipeline…")
            settings = self._settings(backend, offline, self.model_var.get().strip())
            if settings.llm_backend == "openai" and not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY missing")
            pipe = RCAPipeline(settings)
            data = load_scenarios()
            scenarios = data["scenarios"]
            total = len(scenarios) * len(MODES)
            done_n = 0
            rows = []
            lines = []
            for scenario in scenarios:
                gt = scenario["ground_truth"]
                for mode in MODES:
                    progress(f"Evaluating {scenario['id']} / {mode}…")
                    try:
                        result = pipe.run_scenario(scenario, mode=mode)
                        row = score_row(result, gt)
                        mark = "OK" if row["localisation_correct"] else "MISS"
                        line = (
                            f"[{mark}] {mode:10} {scenario['id']:24} "
                            f"-> {result.final_fault_type}@{result.final_device}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        row = {
                            "scenario_id": scenario["id"],
                            "mode": mode,
                            "predicted_fault": "error",
                            "predicted_device": None,
                            "truth_fault": gt["fault_type"],
                            "truth_device": gt.get("device"),
                            "localisation_correct": False,
                            "keyword_coverage": 0.0,
                            "hallucination_rate": 1.0,
                            "evidence_faithfulness": 0.0,
                            "elapsed_ms": 0.0,
                            "explanation": str(exc),
                        }
                        line = f"[ERR] {mode:10} {scenario['id']:24} -> {exc}"
                    rows.append(row)
                    lines.append(line)
                    done_n += 1
                    self.set_progress_fraction(
                        done_n, total, f"{done_n}/{total}: {scenario['id']} ({mode})"
                    )

                    def _append(L=line):
                        self.eval_out.insert("end", L + "\n")
                        self.eval_out.see("end")

                    self.after(0, _append)
            progress("Writing evaluation report + figures…")
            out_dir = ROOT / "results" / "gui_eval"
            path = write_report(rows, out_dir)
            md = (out_dir / "evaluation_report.md").read_text()
            figs = sorted((out_dir / "figures").glob("*.png")) if (out_dir / "figures").exists() else []
            fig_note = (
                f"\n\nAlso wrote {len(figs)} chart(s) under {out_dir / 'figures'}"
                if figs
                else "\n\n(No charts — run Generate figures on Results tab if needed)"
            )
            return "\n".join(lines) + "\n\n" + md + fig_note, str(path)

        def done(res):
            text, path = res
            self.eval_out.delete("1.0", "end")
            self.eval_out.insert("1.0", text)
            self.set_status(f"Evaluation written to {path}")
            self.activity_var.set("Evaluation complete")
            self.phase_var.set(path)
            self.refresh_results()
            messagebox.showinfo(
                "Evaluation complete",
                f"Report saved:\n{path}\n\n"
                "Tables/charts are under results/gui_eval/ "
                "(or use Results → Generate figures).",
            )

        self._worker(work, done, task="Full evaluation")

    # ------------------------------------------------------------- results
    def refresh_results(self) -> None:
        self.results_list.delete(0, "end")
        results = ROOT / "results"
        if not results.exists():
            return
        patterns = ("*.json", "*.md", "*.csv", "*.tex", "*.png")
        files: list[Path] = []
        for pat in patterns:
            files.extend(results.rglob(pat))
        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
        seen = set()
        for f in files:
            rel = str(f.relative_to(ROOT))
            if rel in seen:
                continue
            seen.add(rel)
            self.results_list.insert("end", rel)

    def _selected_eval_report(self) -> Path | None:
        sel = self.results_list.curselection()
        if sel:
            path = ROOT / self.results_list.get(sel[0])
            if path.name == "evaluation_report.json" and path.exists():
                return path
            if path.suffix == ".json" and "evaluation_report" in path.name and path.exists():
                return path
        # Fallbacks commonly used by CLI / GUI
        for candidate in (
            ROOT / "results" / "evaluation_report.json",
            ROOT / "results" / "gui_eval" / "evaluation_report.json",
        ):
            if candidate.exists():
                return candidate
        return None

    def generate_figures(self) -> None:
        report = self._selected_eval_report()
        if report is None:
            messagebox.showwarning(
                "Generate figures",
                "No evaluation_report.json found.\n"
                "Run Evaluate first, or select an evaluation_report.json in the list.",
            )
            return

        def work(progress):
            import sys

            sys.path.insert(0, str(ROOT))
            from evaluation.plot_results import export_all

            progress(f"Generating tables/charts from {report.relative_to(ROOT)}…")
            result = export_all(report, report.parent)
            lines = [
                f"Source: {report}",
                f"Output dir: {result['out_dir']}",
                "",
                "Tables:",
            ]
            for p in result["tables"].values():
                lines.append(f"  - {p}")
            lines.append("Figures:")
            for p in result["figures"]:
                lines.append(f"  - {p}")
            return "\n".join(lines), str(result["out_dir"] / "figures")

        def done(res):
            text, fig_dir = res
            self.results_view.delete("1.0", "end")
            self.results_view.insert("1.0", text)
            self.refresh_results()
            self.set_status(f"Figures written to {fig_dir}")
            self.activity_var.set("Figures ready")
            messagebox.showinfo("Figures generated", f"Charts saved under:\n{fig_dir}")

        self._worker(work, done, task="Generate figures")

    def open_figures_folder(self) -> None:
        report = self._selected_eval_report()
        candidates = []
        if report is not None:
            candidates.append(report.parent / "figures")
        candidates.extend(
            [
                ROOT / "results" / "figures",
                ROOT / "results" / "gui_eval" / "figures",
            ]
        )
        for folder in candidates:
            if folder.exists():
                try:
                    if sys.platform.startswith("linux"):
                        subprocess.Popen(["xdg-open", str(folder)])
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", str(folder)])
                    else:
                        webbrowser.open(folder.as_uri())
                except Exception:  # noqa: BLE001
                    webbrowser.open(folder.as_uri())
                self.set_status(f"Opened {folder}")
                return
        messagebox.showinfo(
            "Figures folder",
            "No figures folder yet.\nSelect an evaluation_report.json and click Generate figures.",
        )

    def open_selected_result(self) -> None:
        sel = self.results_list.curselection()
        if not sel:
            messagebox.showinfo("Results", "Select a file in the list.")
            return
        rel = self.results_list.get(sel[0])
        path = ROOT / rel
        if path.suffix.lower() == ".png":
            try:
                if sys.platform.startswith("linux"):
                    subprocess.Popen(["xdg-open", str(path)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    webbrowser.open(path.as_uri())
            except Exception:  # noqa: BLE001
                webbrowser.open(path.as_uri())
            self.set_status(f"Opened image {rel}")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2)
            except json.JSONDecodeError:
                pass
        self.results_view.delete("1.0", "end")
        self.results_view.insert("1.0", text[:20000])


def main() -> None:
    os.environ.setdefault("LLM_BACKEND", "ollama")
    app = CampusRCAGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
