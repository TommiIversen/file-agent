from busylight_core import BlinkStick, Light

# Find multi-LED devices
multi_led_devices = []
for light in Light.all_lights():
    if hasattr(light, 'on') and 'led' in light.on.__annotations__:
        multi_led_devices.append(light)

if multi_led_devices:
    device = multi_led_devices[0]

    # Control individual LEDs (if supported)
    device.on((255, 0, 0), led=0)    # First LED red
    device.on((0, 255, 0), led=1)    # Second LED green
    device.on((0, 0, 255), led=2)    # Third LED blue