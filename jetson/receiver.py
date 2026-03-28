"""
Compatibility wrapper for the Jetson bridge entrypoint.

The active deployable bridge implementation lives in pico_llm_bridge.py so the
entire `jetson/` folder can be copied into the Jetson bridge directory.
"""

from pico_llm_bridge import main


if __name__ == "__main__":
    raise SystemExit(main())
