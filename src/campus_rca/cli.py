from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from campus_rca.config import get_settings
from campus_rca.models import ProbeSpec
from campus_rca.pipeline import RCAPipeline, load_scenarios

app = typer.Typer(add_completion=False, help="Campus RCA: Batfish + rules + LLM")
console = Console()


@app.command("list-scenarios")
def list_scenarios() -> None:
    data = load_scenarios()
    table = Table(title="Campus fault scenarios")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Fault")
    for s in data["scenarios"]:
        table.add_row(s["id"], s["name"], s["ground_truth"]["fault_type"])
    console.print(table)


@app.command()
def diagnose(
    scenario: str = typer.Argument(..., help="Scenario id from ground_truth/scenarios.yaml"),
    mode: str = typer.Option("hybrid", help="rule_only | llm_only | hybrid"),
    offline: bool = typer.Option(False, help="Use synthetic/cached evidence (no Batfish)"),
    out: Optional[Path] = typer.Option(None, help="Write JSON result path"),
) -> None:
    settings = get_settings().model_copy(update={"use_batfish": False} if offline else {})
    data = load_scenarios()
    matching = next((s for s in data["scenarios"] if s["id"] == scenario), None)
    if not matching:
        console.print(f"[red]Unknown scenario:[/red] {scenario}")
        raise typer.Exit(1)

    pipe = RCAPipeline(settings)
    result = pipe.run_scenario(matching, mode=mode)

    console.print(
        Panel.fit(
            f"[bold]{result.final_fault_type}[/bold] on [cyan]{result.final_device}[/cyan]\n\n"
            f"{result.final_explanation}",
            title=f"{mode} · {scenario}",
        )
    )
    if result.remediation:
        console.print("[bold]Remediation (human approval required):[/bold]")
        for step in result.remediation:
            console.print(f"  • {step}")
    console.print(f"[dim]elapsed={result.elapsed_ms:.0f}ms source={result.evidence.source}[/dim]")

    payload = result.model_dump()
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))
        console.print(f"Wrote {out}")


@app.command()
def adhoc(
    symptom: str = typer.Option(..., "--symptom", "-s"),
    src: str = typer.Option(..., "--src"),
    dst: str = typer.Option(..., "--dst"),
    snapshot: Path = typer.Option(..., exists=True, file_okay=False),
    mode: str = typer.Option("hybrid"),
    port: Optional[int] = typer.Option(None),
    proto: str = typer.Option("TCP"),
    app: Optional[str] = typer.Option(None, help="e.g. HTTP"),
) -> None:
    settings = get_settings()
    probe = ProbeSpec(
        src_ip=src,
        dst_ip=dst,
        dst_port=port,
        ip_protocol=proto,
        applications=[app] if app else [],
    )
    pipe = RCAPipeline(settings)
    result = pipe.run(
        mode=mode,
        scenario_id="adhoc",
        symptom=symptom,
        snapshot_dir=snapshot,
        probe=probe,
    )
    console.print_json(data=result.model_dump())


@app.command("check-llm")
def check_llm() -> None:
    """Verify the configured LLM backend (especially Ollama) is reachable."""
    from campus_rca.llm import get_llm_backend
    from campus_rca.llm.backend import OllamaBackend

    settings = get_settings()
    console.print(f"backend=[cyan]{settings.llm_backend}[/cyan] model=[cyan]{settings.ollama_model if settings.llm_backend=='ollama' else settings.openai_model}[/cyan]")
    backend = get_llm_backend(settings)
    if isinstance(backend, OllamaBackend):
        try:
            info = backend.ping()
            console.print(info)
            names = " ".join(info["models"])
            if settings.ollama_model not in names and f"{settings.ollama_model}:" not in names:
                # allow tag suffix match e.g. llama3.1:latest
                ok = any(
                    m == settings.ollama_model or m.startswith(settings.ollama_model + ":")
                    for m in info["models"]
                )
                if not ok:
                    console.print(
                        f"[yellow]Model '{settings.ollama_model}' not pulled.[/yellow] "
                        f"Run: ./scripts/setup_ollama.sh"
                    )
                    raise typer.Exit(2)
            raw = backend.complete(
                'Reply with JSON only: {"ok": true, "backend": "ollama"}',
                "healthcheck",
            )
            console.print(Panel.fit(raw, title="ollama response"))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Ollama check failed:[/red] {exc}")
            raise typer.Exit(1)
    else:
        console.print(f"[green]Backend {type(backend).__name__} loaded[/green]")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn

    uvicorn.run("campus_rca.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
