"""Allow `python -m efficientroute`, which does not depend on the editable install."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
