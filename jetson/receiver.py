"""
SPARK Jetson Brain — UART packet receiver.

Reads the SPARK serial stream arriving from the Pico Hub and dispatches
decoded packets to JetsonDB.

Run on the Jetson:
    python jetson/receiver.py --port /dev/ttyS0 --db jetson_spark.db
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.protocol import PacketParser, PKT_WINDOW_NEW, PKT_WINDOW_UPDATE, PKT_BUTTON_PRESS
from jetson.db_manager import JetsonDB

logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/ttyS0"   # Jetson Nano/Orin UART0; adjust for your board
DEFAULT_BAUD = 115200


def run(port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
        db_path: str = "jetson_spark.db") -> None:

    try:
        import serial
    except ImportError:
        logger.error("pyserial not installed — run: pip install pyserial")
        sys.exit(1)

    db = JetsonDB(db_path)

    def handle_packet(pkt: dict) -> None:
        t = pkt["type"]
        if t == PKT_WINDOW_NEW:
            db.on_window_new(pkt["app_name"], pkt["title"], pkt["text"])
        elif t == PKT_WINDOW_UPDATE:
            db.on_window_update(pkt["text"])
        elif t == PKT_BUTTON_PRESS:
            db.on_button_press(pkt["button_id"])

    parser = PacketParser(on_packet=handle_packet)

    def _shutdown(sig, frame):
        logger.info("Shutting down…")
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(f"Opening {port} @ {baud} baud")
    with serial.Serial(port, baud, timeout=1) as ser:
        logger.info("SPARK Jetson receiver running — waiting for packets")
        while True:
            chunk = ser.read(256)
            if chunk:
                parser.feed(chunk)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    )
    p = argparse.ArgumentParser(description="SPARK Jetson packet receiver")
    p.add_argument("--port", default=DEFAULT_PORT,
                   help="Serial port (default: %(default)s)")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                   help="Baud rate (default: %(default)s)")
    p.add_argument("--db",   default="jetson_spark.db",
                   help="SQLite database path (default: %(default)s)")
    args = p.parse_args()
    run(args.port, args.baud, args.db)
