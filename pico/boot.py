import supervisor
import usb_cdc
import usb_hid

try:
    from pico.usb_config import SPARK_PID, SPARK_VID, build_custom_hid_device
except ImportError:
    from usb_config import SPARK_PID, SPARK_VID, build_custom_hid_device


supervisor.set_usb_identification(
    manufacturer="SPARK",
    product="SPARK Pico Hub",
    vid=SPARK_VID,
    pid=SPARK_PID,
)

usb_cdc.enable(console=False, data=True)
usb_hid.enable((build_custom_hid_device(usb_hid),))
