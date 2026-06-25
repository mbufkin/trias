"""Allow `python -m trias` when PYTHONPATH includes src/."""

from .cli import main

if __name__ == "__main__":
    main()
