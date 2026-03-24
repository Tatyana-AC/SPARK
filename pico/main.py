"""
SPARK Pico Hub - serial relay behavioral reference.

This file documents the relay and button-injection logic that runs on the
single Pico Hub device (RP2040, CircuitPython firmware target,
VID 0xC4C4 / PID 0x5350).
The deployed firmware is a CircuitPython `boot.py` + `code.py` pair.
This file remains a readable Python reference for the expected Pico-side
behavior and protocol handling.

Role: sit between the Host PC (USB CDC) and the Jetson Brain (UART),
forwarding all Host context packets transparently while injecting
BUTTON_PRESS (0x05) packets whenever a physical button is pressed.
Host uploads are handled separately via the custom Raw HID interface of
the same CircuitPython device. `SUBMIT_TEXT` uploads are validated and
acknowledged over Raw HID only. The host app renders released text
locally after a successful upload. `PING` uploads respond with a short
status string.

Wiring (single Pico Hub)
------------------------
  USB  <-> Host PC  - CDC serial   (context relay, /dev/tty.usbmodem*)
                    - Custom HID   (GET_INFO/BEGIN_UPLOAD/.../STATUS)
  GP0 (TX) -> Jetson RX   (UART0, 115200 baud)
  GP1 (RX) <- Jetson TX   (reserved, future ACK)
  GP14 - Button 0  (active-low, internal pull-up)
  GP15 - Button 1
  GP16 - Button 2
  GP17 - Button 3

This file is reference logic, not the literal deployed CircuitPython
firmware file set.
"""

import sys
import select
import struct
import machine
import utime

# UART to Jetson Brain
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))

# Physical buttons (active-low, pulled high internally)
BUTTON_PINS = [14, 15, 16, 17]
buttons = [machine.Pin(p, machine.Pin.IN, machine.Pin.PULL_UP) for p in BUTTON_PINS]
btn_prev = [1] * len(buttons)  # 1 = released


# CRC-8/MAXIM (mirrored from core/protocol.py, no imports needed)
def _crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x01:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
    return crc & 0xFF


def _build_button_press(button_id):
    """Build a BUTTON_PRESS (0x05) wire packet."""
    payload = struct.pack("<B", button_id)  # uint8_t
    header = struct.pack("<2sBH", b"SP", 0x05, len(payload))  # magic + type + len
    body = header + payload
    return body + struct.pack("<B", _crc8(body))  # CRC8


# USB -> UART passthrough
_usb_poll = select.poll()
_usb_poll.register(sys.stdin, select.POLLIN)


def _relay_usb_to_uart():
    """Forward any pending bytes from USB CDC to UART (non-blocking)."""
    events = _usb_poll.poll(0)
    if events:
        chunk = sys.stdin.buffer.read(64)
        if chunk:
            uart.write(chunk)


# Button edge detection
def _check_buttons():
    """Detect falling edge (button pressed) and send BUTTON_PRESS packet."""
    for i, pin in enumerate(buttons):
        current = pin.value()
        if btn_prev[i] == 1 and current == 0:  # falling edge -> pressed
            uart.write(_build_button_press(i))
        btn_prev[i] = current


# Main loop
while True:
    _relay_usb_to_uart()
    _check_buttons()
    utime.sleep_ms(10)  # ~100 Hz polling; well above button debounce needs
