# Luck Jingle Printer for Home Assistant

A custom Home Assistant integration that sends text, PDF pages, and raster
images directly to Luck Jingle-compatible BLE thermal printers. It adds a
**Print text** action and a test-print button to the printer's device page.

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
6. Select **LPC50 (ORICO C50)**. Home Assistant scans for a matching BLE
   advertisement and selects the printer automatically. If multiple matching
   printers are nearby, choose the one to configure.
7. Choose **Automatic** or a Bluetooth source that sees the printer. For an
   existing entry, change this from the integration's **Configure** options.

The QR label is not needed for setup. It contains the printer name and its
Bluetooth Classic address; Home Assistant discovers and connects to the
separate BLE address automatically.

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
- If Home Assistant has multiple Bluetooth adapters, select the source that
  reports the printer. The selector lists sources currently seeing that printer;
  **Automatic** keeps Home Assistant's default source selection.
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

## Print from other network devices

When adding the integration, enable **Enable authenticated network printing**
to expose a text-print endpoint through Home Assistant's existing HTTP server.
The relay is off by default. For an existing printer, enable it from the
integration's **Configure** options without removing and re-adding the device.
When enabled, a diagnostic **Network print relay** binary sensor is added to
the printer device.

The endpoint accepts UTF-8 text jobs as JSON and raw PDF or raster-image files.
It uses Home Assistant's normal bearer-token authentication:

```sh
curl -X POST \
  -H "Authorization: Bearer YOUR_HOME_ASSISTANT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello from the network","density":1,"feed":80}' \
  "http://HOME_ASSISTANT:8123/api/luck_jingle/print/CONFIG_ENTRY_ID"
```

Print a PDF or PNG directly with `curl`:

```sh
curl --fail -X POST \
  -H "Authorization: Bearer YOUR_HOME_ASSISTANT_ACCESS_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @document.pdf \
  "http://HOME_ASSISTANT:8123/api/luck_jingle/print/CONFIG_ENTRY_ID"
```

For an image, use its MIME type, such as `image/png` or `image/jpeg`, and pass
the file with `--data-binary`. PDF pages and supported image frames are printed
as separate labels. Supported raster formats are BMP, GIF, JPEG, PNG, TIFF, and
WebP. Documents are limited to 8 MiB and 20 pages/frames; images are resized to
fit the printer's 384-pixel width and 1024-dot maximum page height. Optional
`density` and `feed` query parameters use the same ranges as the text action.
Multi-page jobs may take a few minutes because the printer transfers each
raster page over BLE.

Create a long-lived access token from your Home Assistant profile. Keep it
private: anyone holding it can use the Home Assistant API. JSON text requests
accept the same `text`, `density`, and `feed` values as
`luck_jingle.print_text`. Use HTTPS when traffic crosses an untrusted network,
and do not expose Home Assistant's HTTP port directly to the Internet. When the
relay is enabled, find the `config_entry_id` in the attributes of its
**Network print relay** entity; that value is used in the endpoint URL and CUPS
device URI.

### Optional CUPS text-only forwarding

CUPS is not installed inside Home Assistant. For a CUPS server on another
Linux device, install `cups/backend/luckjingle` into CUPS's backend directory,
make it executable, and configure a text-only queue whose device URI is
`luckjingle://CONFIG_ENTRY_ID`. Create `/etc/cups/luckjingle.conf` readable only
by the CUPS service account:

```ini
[homeassistant]
url = http://HOME_ASSISTANT:8123
token = YOUR_HOME_ASSISTANT_ACCESS_TOKEN
```

The backend forwards UTF-8 text, PDF, and supported raster-image jobs to the
authenticated endpoint. It supports copies and form-feed-separated text pages.
Configure a raw/no-conversion queue so CUPS passes PDF and image bytes through
unchanged; filtered printer-language jobs are not supported. Restart CUPS
after installing the backend and creating its configuration file.

## Linux BlueZ connection issues

Some dual-mode LuckPrinter devices advertise both Bluetooth Classic and BLE.
BlueZ can choose the Classic bearer for its initial connection, even though
printing requires BLE GATT. The integration now prefers LE for this printer's
BlueZ device entry, disconnects a stale link on the exact selected adapter, and
tries other visible Home Assistant Bluetooth sources if the preferred source
cannot connect. This is a per-printer preference; it does not disable Classic
Bluetooth for other devices.

If connection attempts still time out, move the printer or Bluetooth adapter
closer. A dedicated USB BLE adapter or Home Assistant Bluetooth proxy can also
improve reception. The source selector is a preference: if that source cannot
connect, the integration may fall back to another source Home Assistant sees.

## Protocol references

- [MiniX / LuckJingle S1 protocol notes](https://github.com/SwapnanilDhol/minixprint/blob/main/PROTOCOL.md)
- [Thermal pocket printer BLE notes](https://github.com/ChiaraCannolee/thermal-pocket-printer-basic)

These references verify the protocol on other LuckPrinter models, not the
ORICO C50. Test with short labels before relying on it for important printing.
