"""Entry point for the frozen .app (double-click opens the GUI)."""
import sys

from tfe_poster.cli import main

if __name__ == "__main__":
    # Finder may pass -psn_… on old macOS; anything that isn't a CLI command opens the GUI.
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if not args or args[0] not in ("process", "batch", "doctor", "gui", "-h", "--help"):
        from tfe_poster.gui.app import run
        sys.exit(run([sys.argv[0]] + args))
    sys.exit(main(args))
