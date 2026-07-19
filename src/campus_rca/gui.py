"""Tkinter UI for Campus RCA — setup, diagnose, evaluate, browse results."""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Optional

from campus_rca import config as config_mod
from campus_rca.config import ROOT, Settings
from campus_rca.pipeline import RCAPipeline, load_scenarios
from campus_rca.setup_checks import (
    gather_setup_report,
    ensure_project_synced,
    pull_ollama_model,
    start_ollama_serve,
)


MODES = ("hybrid", "rule_only", "llm_only")
# Masters prototype: real backends only (no mock in the UI)
BACKENDS = ("ollama", "openai")


class CampusRCAGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Campus RCA — Batfish + Rules + LLM")
        self.geometry("980x720")
        self.minsize(860, 600)

        self._busy = False
        self._scenarios: list[dict[str, Any]] = []
        self._last_result: Optional[dict[str, Any]] = None

        self._build()
        self.after(200, self.refresh_setup)
        self.after(400, self.reload_scenarios)

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
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)
        self.progress.pack(side="right")

    def _build_setup(self) -> None:
        top = ttk.Frame(self.tab_setup)
        top.pack(fill="x")
        ttk.Button(top, text="Re-check system", command=self.refresh_setup).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(top, text="uv sync", command=self.do_uv_sync).pack(side="left", padx=6)
        ttk.Button(top, text="Start Ollama", command=self.do_start_ollama).pack(
            side="left", padx=6
        )
        ttk.Button(top, text="Pull Ollama model", command=self.do_pull_model).pack(
            side="left", padx=6
        )

        self.platform_var = tk.StringVar(value="")
        ttk.Label(self.tab_setup, textvariable=self.platform_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(10, 4)
        )

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
        ttk.Entry(form, textvariable=self.model_var, width=30).grid(
            row=row, column=1, sticky="w", padx=6, pady=3
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
        ttk.Button(btns, text="Run diagnosis", command=self.run_diagnose).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(btns, text="Save JSON…", command=self.save_last_result).pack(side="left")

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
        ttk.Checkbutton(
            opts, text="Offline evidence", variable=self.eval_offline
        ).pack(side="left", padx=(0, 12))
        ttk.Label(opts, text="Backend").pack(side="left")
        ttk.Combobox(
            opts,
            textvariable=self.eval_backend,
            values=BACKENDS,
            state="readonly",
            width=12,
        ).pack(side="left", padx=6)

        ttk.Button(self.tab_eval, text="Run full evaluation", command=self.run_eval).pack(
            anchor="w", pady=8
        )
        self.eval_out = scrolledtext.ScrolledText(self.tab_eval, wrap="word")
        self.eval_out.pack(fill="both", expand=True)

    def _build_results(self) -> None:
        top = ttk.Frame(self.tab_results)
        top.pack(fill="x")
        ttk.Button(top, text="Refresh list", command=self.refresh_results).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(top, text="Open selected", command=self.open_selected_result).pack(
            side="left"
        )

        self.results_list = tk.Listbox(self.tab_results, height=8)
        self.results_list.pack(fill="x", pady=6)
        self.results_view = scrolledtext.ScrolledText(self.tab_results, wrap="word")
        self.results_view.pack(fill="both", expand=True)
        self.refresh_results()

    # -------------------------------------------------------------- helpers
    def log_setup(self, msg: str) -> None:
        self.setup_log.insert("end", msg + "\n")
        self.setup_log.see("end")

    def set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _settings(self, backend: str, offline: bool, model: str) -> Settings:
        config_mod.get_settings.cache_clear()
        base = Settings()
        updates: dict[str, Any] = {
            "llm_backend": backend,  # type: ignore[dict-item]
            "use_batfish": not offline,
            "ollama_model": model,
        }
        return base.model_copy(update=updates)

    def _worker(self, fn, on_done=None) -> None:
        if self._busy:
            messagebox.showinfo("Busy", "Please wait for the current task to finish.")
            return

        def run():
            self.after(0, lambda: self.set_busy(True))
            err = None
            result = None
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                err = exc
            def finish():
                self.set_busy(False)
                if err:
                    messagebox.showerror("Error", str(err))
                    self.set_status(f"Error: {err}")
                elif on_done:
                    on_done(result)
            self.after(0, finish)

        threading.Thread(target=run, daemon=True).start()

    # --------------------------------------------------------------- setup
    def refresh_setup(self) -> None:
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
        self.log_setup(f"Checked system — {ready}")
        # Prefill offline if Batfish down
        batfish_ok = any(c.name == "Batfish" and c.ok for c in report.checks)
        if not batfish_ok:
            self.offline_var.set(True)
            self.eval_offline.set(True)

    def do_uv_sync(self) -> None:
        def work():
            self.after(0, lambda: self.set_status("Running uv sync…"))
            return ensure_project_synced()

        def done(res):
            ok, detail = res
            self.log_setup(detail[-1500:] if detail else "")
            self.set_status("uv sync OK" if ok else "uv sync failed")
            self.refresh_setup()
            if not ok:
                messagebox.showerror("uv sync failed", detail[-800:])

        self._worker(work, done)

    def do_start_ollama(self) -> None:
        def work():
            return start_ollama_serve()

        def done(res):
            ok, detail = res
            self.log_setup(f"Ollama: {detail}")
            self.refresh_setup()
            if not ok:
                messagebox.showerror("Ollama", detail)

        self._worker(work, done)

    def do_pull_model(self) -> None:
        model = self.model_var.get().strip() or "llama3.2:3b"

        def work():
            self.after(0, lambda: self.set_status(f"Pulling {model}…"))
            return pull_ollama_model(model)

        def done(res):
            ok, detail = res
            self.log_setup(detail[-1500:] if detail else f"pulled {model}")
            self.set_status("Model ready" if ok else "Pull failed")
            self.refresh_setup()
            if not ok:
                messagebox.showerror("Pull failed", detail[-800:])

        self._worker(work, done)

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

        def work():
            self.after(0, lambda: self.set_status(f"Diagnosing {sid} ({mode})…"))
            settings = self._settings(backend, offline, model)
            if settings.llm_backend == "openai" and not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY missing in environment / .env")
            sc = next(s for s in load_scenarios()["scenarios"] if s["id"] == sid)
            pipe = RCAPipeline(settings)
            result = pipe.run_scenario(sc, mode=mode)
            out = ROOT / "results" / f"gui_{sid}_{mode}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result.model_dump_json(indent=2))
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
            lines += ["", f"Saved: {path}", "", "--- raw JSON ---", json.dumps(payload, indent=2)[:8000]]
            self.diag_out.insert("1.0", "\n".join(lines))
            self.set_status(f"Done: {payload['final_fault_type']} @ {payload['final_device']}")
            self.refresh_results()
            self.notebook.select(self.tab_diag)

        self._worker(work, done)

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

        def work():
            self.after(0, lambda: self.set_status("Running evaluation (may take a while)…"))
            # Import here so GUI starts even if eval deps shift
            import sys

            sys.path.insert(0, str(ROOT))
            from evaluation.metrics import score_row, write_report

            settings = self._settings(backend, offline, self.model_var.get().strip())
            if settings.llm_backend == "openai" and not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY missing")
            pipe = RCAPipeline(settings)
            data = load_scenarios()
            rows = []
            lines = []
            for scenario in data["scenarios"]:
                gt = scenario["ground_truth"]
                for mode in MODES:
                    result = pipe.run_scenario(scenario, mode=mode)
                    row = score_row(result, gt)
                    rows.append(row)
                    mark = "OK" if row["localisation_correct"] else "MISS"
                    line = (
                        f"[{mark}] {mode:10} {scenario['id']:24} "
                        f"-> {result.final_fault_type}@{result.final_device}"
                    )
                    lines.append(line)
                    self.after(0, lambda L=line: (self.eval_out.insert("end", L + "\n"), self.eval_out.see("end")))
            out_dir = ROOT / "results" / "gui_eval"
            path = write_report(rows, out_dir)
            md = (out_dir / "evaluation_report.md").read_text()
            return "\n".join(lines) + "\n\n" + md, str(path)

        def done(res):
            text, path = res
            self.eval_out.delete("1.0", "end")
            self.eval_out.insert("1.0", text)
            self.set_status(f"Evaluation written to {path}")
            self.refresh_results()
            messagebox.showinfo("Evaluation complete", f"Report saved:\n{path}")

        self._worker(work, done)

    # ------------------------------------------------------------- results
    def refresh_results(self) -> None:
        self.results_list.delete(0, "end")
        results = ROOT / "results"
        if not results.exists():
            return
        files = sorted(results.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        files += sorted(results.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        seen = set()
        for f in files:
            rel = str(f.relative_to(ROOT))
            if rel in seen:
                continue
            seen.add(rel)
            self.results_list.insert("end", rel)

    def open_selected_result(self) -> None:
        sel = self.results_list.curselection()
        if not sel:
            messagebox.showinfo("Results", "Select a file in the list.")
            return
        rel = self.results_list.get(sel[0])
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2)
            except json.JSONDecodeError:
                pass
        self.results_view.delete("1.0", "end")
        self.results_view.insert("1.0", text[:20000])


def main() -> None:
    # Prefer Ollama for masters runs when env is unset
    os.environ.setdefault("LLM_BACKEND", "ollama")
    app = CampusRCAGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
