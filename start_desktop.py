"""Windows desktop entry point; kept separate from the developer web launcher."""
from etd_sync.desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
