"""
Example usage of the RawHIDListener for SPARK device.

This demonstrates how to:
1. Create a listener for the SPARK device
2. Register callbacks for different event types
3. Start/stop the background thread
4. Send reports back to the device
"""

import logging
import sys
import time

from host_pc.raw_hid import (
    create_listener,
    ButtonEvent,
    EncoderEvent,
    ParameterUpdateEvent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s"
)
logger = logging.getLogger(__name__)


def on_button_press(event: ButtonEvent) -> None:
    """Handle button press/release events."""
    logger.info(f"🔘 Button event: {event}")


def on_encoder_change(event: EncoderEvent) -> None:
    """Handle encoder rotation events."""
    logger.info(f"🔄 Encoder event: {event}")


def on_param_update(event: ParameterUpdateEvent) -> None:
    """Handle parameter update events."""
    logger.info(f"📊 Parameter update: {event}")


def on_error(error_msg: str) -> None:
    """Handle errors from the listener."""
    logger.error(f"⚠️  Error: {error_msg}")


def main():
    """Main example: connect to device and listen for events."""
    # Check for --mock flag to use mock device instead of real hardware
    use_mock = "--mock" in sys.argv

    # Create listener (with or without mock)
    listener = create_listener(mock=use_mock, auto_reconnect=True)

    # Register callbacks
    listener.on_button_press(on_button_press)
    listener.on_encoder_change(on_encoder_change)
    listener.on_param_update(on_param_update)
    listener.on_error(on_error)

    # Start listening in background thread
    if not listener.start():
        logger.error("Failed to start listener")
        return 1

    logger.info("Listening for SPARK device events... (Ctrl+C to stop)")

    try:
        # Main thread can do other work while listener runs in background
        while True:
            time.sleep(1)

            # Example: send a report to device (e.g., LED feedback)
            # Uncomment to test:
            # listener.send_report(b'\x50\x01\x00\x00\x00')

    except KeyboardInterrupt:
        logger.info("Stopping listener...")
    finally:
        listener.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
