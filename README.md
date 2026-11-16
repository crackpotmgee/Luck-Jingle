# Luck Jingle Printer for Home Assistant

A custom Home Assistant integration that sends text labels directly to Luck
Jingle-compatible BLE thermal printers. It adds a **Print text** action and a
test-print button to the printer's device page.

The BLE commands are based on community reverse-engineered LuckPrinter protocol
notes. The ORICO C50 has not been independently tested with this integration;
printer models that use a different print width or firmware may not work.

This is a local Git repository. To install it through HACS, first publish it to
GitHub (or another supported GitHub host).

## Install with HACS

[![Open your Home Assistant instance and show the Luck Jingle Printer
integration inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=crackpotmgee&repository=luck-jingle&category=integration)

1. In HACS, open **Integrations** and choose the menu in the upper-right.
2. Select **Custom repositories**.
3. Add this repository's GitHub URL and choose **Integration**.
4. Install **Luck Jingle Printer**, then restart Home Assistant.
5. In **Settings → Devices & services**, choose **Add integration** and search
   for **Luck Jingle Printer**.
6. Scan the printer's QR label with your phone and paste its contents into the
   setup form. The C50 label format is
   `LPC50_3F3D?12:22:33:4C:3D:3F`.

The address encoded on this label is the printer's Bluetooth Classic address,
not its BLE address. Setup uses the name in the QR code to find the printer's
BLE advertisement and stores that BLE address instead. You can also enter a
BLE address directly.

For manual installation, copy `custom_components/luck_jingle` into the
`custom_components` directory in your Home Assistant configuration folder and
restart Home Assistant.

## Bluetooth requirements

- Home Assistant must have access to a Bluetooth adapter and be able to see the
  printer. For Docker installations, configure Bluetooth access for Home
  Assistant or use a Home Assistant Bluetooth proxy.
- Keep the printer powered on and near the adapter when printing.
- Home Assistant must see the printer's BLE advertisement during setup. The QR
  payload identifies the printer by name so setup can resolve its BLE address,
  even though the QR contains a different Bluetooth Classic address.
- Linux/BlueZ can fail to connect to some dual-mode printers because it attempts
  Bluetooth Classic first. See the [BlueZ note](#linux-bluez-connect-errors).

## Print from an automation

Call the `luck_jingle.print_text` action:

```yaml
action: luck_jingle.print_text
data:
  text: "Shopping list\nMilk\nBread"
  density: 1
  feed: 80
```

The text is wrapped to fit the 384-pixel print width. `density` accepts `0`
(light), `1` (normal), or `2` (dark). `feed` is 0–255 dots. If multiple
printers are configured, set `config_entry_id` to the desired config entry ID.
When only one printer is configured, it is selected automatically.

## Linux BlueZ connect errors

Some dual-mode LuckPrinter devices advertise both Bluetooth Classic and BLE.
On Linux, BlueZ may try the Classic printer profile first and fail before a BLE
connection is established. Remove any stale paired printer entry and retry. A
dedicated BLE adapter or Bluetooth proxy can also avoid conflicts; changing
BlueZ's adapter mode affects other Bluetooth devices and should only be done
with care.

## Protocol references

- [MiniX / LuckJingle S1 protocol notes](https://github.com/SwapnanilDhol/minixprint/blob/main/PROTOCOL.md)
- [Thermal pocket printer BLE notes](https://github.com/ChiaraCannolee/thermal-pocket-printer-basic)

These references verify the protocol on other LuckPrinter models, not the
ORICO C50. Test with short labels before relying on it for important printing.
