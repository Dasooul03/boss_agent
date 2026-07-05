from __future__ import annotations

import importlib.util


REQUIRED_IMPORTS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "ollama": "ollama",
    "pypdf": "pypdf",
    "python-multipart": "multipart",
}


def main() -> int:
    missing = [
        package
        for package, module in REQUIRED_IMPORTS.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        print("Missing Python packages: " + ", ".join(missing))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
