from pathlib import Path

import nbformat


def test_notebook_contains_complete_current_sources():
    root = Path(__file__).resolve().parents[1]
    book = nbformat.read(root / "LLM_Theatre.ipynb", as_version=4)
    modules = {}
    for cell in book.cells:
        if cell.cell_type == "code" and cell.source.startswith("%%bunker_module "):
            first, source = cell.source.split("\n", 1)
            name = first.split()[1]
            modules[name] = source
            assert source == (root / "bunker" / f"{name}.py").read_text()
            compile(source, f"{name}.py", "exec")
    assert set(modules) == {
        "domain",
        "cards",
        "rules",
        "storage",
        "context",
        "provider",
        "engine",
        "web",
    }
    assert all(
        output.output_type != "error"
        for cell in book.cells
        if cell.cell_type == "code"
        for output in cell.outputs
    )
