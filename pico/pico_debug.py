import usb_cdc

try:
    from pico.protocol import build_debug
except ImportError:
    from protocol import build_debug

_data = usb_cdc.data


def dbg(msg):
    """Send a debug message to the host over CDC data."""
    if _data is None:
        return
    try:
        _data.write(build_debug(str(msg)))
    except Exception:
        pass
