#!/usr/bin/env python3
"""Generate all test fixtures for benchmarks."""

import subprocess
import sys
from pathlib import Path


def run_generator(script_name: str) -> None:
    """Run a generator script."""
    script_path = Path(__file__).parent / script_name
    print(f"\n{'=' * 60}")
    print(f"Running {script_name}...")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=script_path.parent,
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"ERROR: {script_name} failed with exit code {result.returncode}")
        sys.exit(1)


def main():
    """Generate all fixtures."""
    base_dir = Path(__file__).parent

    print("Generating benchmark test fixtures...")
    print(f"Output directory: {base_dir.absolute()}")

    # Generate Python fixtures
    run_generator("generate_python.py")

    # Generate Rust fixtures
    run_generator("generate_rust.py")

    # Generate JavaScript fixtures
    run_generator("generate_js.py")

    print("\n" + "=" * 60)
    print("All fixtures generated successfully!")
    print("=" * 60)

    # List generated files
    for lang in ["python", "rust", "javascript"]:
        lang_dir = base_dir / lang
        if lang_dir.exists():
            print(f"\n{lang.upper()} files:")
            for f in sorted(
                lang_dir.glob(
                    "*.py" if lang == "python" else "*.rs" if lang == "rust" else "*.js"
                )
            ):
                size = f.stat().st_size / 1024
                with open(f) as file:
                    lines = len(file.readlines())
                print(f"  {f.name}: {lines} lines, {size:.1f} KB")


if __name__ == "__main__":
    main()
