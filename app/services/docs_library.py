# app/services/docs_library.py — placeholder service
from pathlib import Path


def list_docs(root: Path) -> list[dict]:
    root = Path(root)
    items = []
    for p in sorted(root.glob("**/*")):
        if p.is_file():
            items.append({"name": p.name, "path": str(p)})
    return items
