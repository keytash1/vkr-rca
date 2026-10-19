"""Operator CLI for the bounded runtime adapter; no model/provider invocation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"cmd/thesis_demo"))
from context_source import ContextError, LokiContextSource, bounded_probe, main

if __name__ == "__main__":
    main()
