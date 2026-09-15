"""Build a source-only interview ZIP from an explicit allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / "dist" / "sphere-rca-agent-submission.zip"
    destination.parent.mkdir(exist_ok=True)
    top_level = ["README.md", "ARCHITECTURE.md", "pyproject.toml", "uv.lock", ".gitignore", ".env.example"]
    paths = [root / name for name in top_level]
    for directory in ["src", "tests", "scripts", "docs"]:
        paths.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, path.relative_to(root))
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert not any(
            name.startswith((".venv/", "outputs/", "data/")) or name == ".env" or name.endswith(".pyc")
            for name in archive.namelist()
        )
        print(
            f"Created {destination.name}: {len(archive.namelist())} files, {destination.stat().st_size} bytes"
        )


if __name__ == "__main__":
    main()
