import supervisor
import usb_cdc
import usb_hid
import usb_midi

print("boot: imports ready")

try:
    from pico.usb_config import SPARK_PID, SPARK_VID, build_custom_hid_device
except ImportError:
    from usb_config import SPARK_PID, SPARK_VID, build_custom_hid_device

print("boot: usb_config ready", hex(SPARK_VID), hex(SPARK_PID))


supervisor.set_usb_identification(
    manufacturer="SPARK",
    product="SPARK Pico Hub",
    vid=SPARK_VID,
    pid=SPARK_PID,
)

print("boot: usb identification set")

usb_cdc.enable(console=False, data=True)
print("boot: usb_cdc enabled console=False data=True")

usb_midi.disable()
print("boot: usb_midi disabled")

usb_hid.disable()
print("boot: usb_hid disabled")

custom_device = build_custom_hid_device(usb_hid)
print("boot: custom hid built", hex(custom_device.usage_page), hex(custom_device.usage))

usb_hid.enable((custom_device,))
print("boot: usb_hid enabled", len(usb_hid.devices))
