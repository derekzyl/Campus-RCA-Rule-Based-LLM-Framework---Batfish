.PHONY: sync demo eval eval-ollama batfish serve ollama check-llm lock gui run

sync:
	uv sync

lock:
	uv lock

run:
	./run.sh

gui:
	uv run campus-rca-gui

demo:
	uv run ./scripts/demo.sh

eval:
	uv run python evaluation/run_eval.py --offline --llm-backend ollama --out results

eval-ollama:
	uv run python evaluation/run_eval.py --offline --llm-backend ollama --out results/ollama

check-llm:
	uv run campus-rca check-llm

ollama:
	./scripts/setup_ollama.sh

batfish:
	./scripts/start_batfish.sh

serve:
	uv run campus-rca serve --host 127.0.0.1 --port 8080
