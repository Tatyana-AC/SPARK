"""
SPARK Pico Hub - transport-only behavioral reference.

This file documents the reduced Pico role after the LCD and physical-button
runtime were removed from the active firmware. The deployed firmware is still a
CircuitPython `boot.py` + `code.py` pair; this file remains a readable sketch of
the same relay-oriented behavior.

Role: sit between the Host PC (USB CDC + custom Raw HID) and the Jetson Brain
(UART), forwarding host CDC bytes to UART, servicing Raw HID upload commands,
and polling the summarize transport.

Wiring (single Pico Hub)
------------------------
  USB  <-> Host PC  - CDC serial   (context relay, /dev/tty.usbmodem*)
                    - Custom HID   (GET_INFO/BEGIN_UPLOAD/.../STATUS)
  GP0 (TX) -> Jetson RX   (UART0, 115200 baud)
  GP1 (RX) <- Jetson TX   (summarize response bytes)

This file is reference logic, not the literal deployed CircuitPython firmware
file set.
"""

import sys
import select
import machine
import utime


uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))

_usb_poll = select.poll()
_usb_poll.register(sys.stdin, select.POLLIN)


def _relay_usb_to_uart():
    """Forward any pending bytes from USB CDC to UART (non-blocking)."""
    events = _usb_poll.poll(0)
    if events:
        chunk = sys.stdin.buffer.read(64)
        if chunk:
            uart.write(chunk)


while True:
    _relay_usb_to_uart()
    utime.sleep_ms(10)
