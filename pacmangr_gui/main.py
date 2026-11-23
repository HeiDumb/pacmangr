"""Entry point for the pacmangr GTK front-end."""

from __future__ import annotations

import sys

from .app import PacmangrGUI
from .core_loader import CORE


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    if len(arguments) > 1 and arguments[1] in {"-V", "--version"}:
        print(f"pacmangr-gui {CORE.VERSION}")
        return 0
    return PacmangrGUI().run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
