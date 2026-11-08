import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ["JUPYTER_PATH"] = str(ROOT / ".venv/share/jupyter")
    book = nbformat.read(ROOT / "LLM_Theatre.ipynb", as_version=4)
    client = NotebookClient(
        book,
        timeout=90,
        kernel_name="bunker",
        resources={"metadata": {"path": str(ROOT)}},
    )
    client.execute()
    nbformat.write(book, ROOT / "LLM_Theatre.ipynb")
    print("Notebook executed in project .venv; RUN_LIVE=False.")


if __name__ == "__main__":
    main()
