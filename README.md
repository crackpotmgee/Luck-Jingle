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
  font_size: 20
  density: 1
  feed: 80
```

`font_size` is 10–30 pixels and defaults to 10; larger text wraps more and
makes taller labels. Newline characters and literal `\n` sequences start new
lines; long lines wrap to fit the 384-pixel print width.
`density` accepts `0` (light), `1` (normal), or `2` (dark). `feed` is 0–255
dots. If multiple printers are configured, set `config_entry_id` to the desired
config entry ID. When only one printer is configured, it is selected
automatically.

## Print from other network devices

When adding the integration, enable **Enable authenticated network printing**
to expose a text-print endpoint through Home Assistant's existing HTTP server.
The relay is off by default. For an existing printer, enable it from the
integration's **Configure** options without removing and re-adding the device.
When enabled, a diagnostic **Network print relay** binary sensor is added to
the printer device.

This does not advertise an IPP, AirPrint, or DNS-SD printer, so the printer
will not appear in devices' network-printer scans. It exposes an authenticated
HTTP API for clients that can send requests to Home Assistant.

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

### Optional: expose a printer queue with CUPS

CUPS can share a virtual IPP printer queue and, with mDNS/AirPrint configured,
advertise that queue to network devices. The ORICO C50 remains a BLE printer;
the queue forwards its jobs through this integration's authenticated HTTP API.

Home Assistant does not include a CUPS server. The simplest setup is a separate
Linux host on the same network as Home Assistant. On Debian or Ubuntu, install
CUPS and Avahi:

```sh
sudo apt update
sudo apt install cups avahi-daemon
```

Install the backend from this repository into CUPS's backend directory:

```sh
sudo install -o root -g root -m 0755 cups/backend/luckjingle \
  /usr/lib/cups/backend/luckjingle
```

Create `/etc/cups/luckjingle.conf` with the Home Assistant base URL and a
long-lived access token:

```ini
[homeassistant]
url = http://HOME_ASSISTANT:8123
token = YOUR_HOME_ASSISTANT_ACCESS_TOKEN
```

Restrict the token file to root, then create and share a raw queue. Replace
`CONFIG_ENTRY_ID` with the ID shown in the **Network print relay** entity:

```sh
sudo chown root:root /etc/cups/luckjingle.conf
sudo chmod 600 /etc/cups/luckjingle.conf
sudo lpadmin -p LuckJingle -E \
  -v "luckjingle://CONFIG_ENTRY_ID" \
  -m raw
sudo lpadmin -p LuckJingle -o printer-is-shared=true
sudo cupsctl --share-printers --remote-any
sudo systemctl enable --now avahi-daemon
sudo systemctl restart cups
```

The backend forwards UTF-8 text, PDF, and supported raster-image jobs. It
supports copies and form-feed-separated text pages. The raw/no-conversion queue
is required so CUPS passes PDF and image bytes through unchanged; filtered
printer-language jobs are not supported.

To check the queue, run `lpstat -p LuckJingle`, then send a text test:

```sh
printf 'Luck Jingle CUPS test\n' | lp -d LuckJingle -o raw
```

Other devices can use the queue at
`ipp://CUPS_HOST:631/printers/LuckJingle`. For Bonjour/AirPrint discovery,
Avahi/mDNS must be reachable on the local network. Allow CUPS TCP port 631 only
from trusted LAN devices and do not expose it to the Internet. Keep the
Home Assistant token private; anyone who obtains it can use the Home Assistant
API.

#### Home Assistant OS add-on

To try the third-party CUPS add-on, add
`https://github.com/MaxWinterstein/homeassistant-addons` under **Settings →
Add-ons → Add-on Store → ⋮ → Repositories**, then install **CUPS Print Server**.
This add-on is not included or supported by this integration. It must also
contain the `luckjingle` CUPS backend and its configuration; installing the
generic add-on alone will not create a working Luck Jingle queue. The
[CUPS Print Server add-on](https://github.com/MaxWinterstein/homeassistant-addons/tree/main/cups)
is marked experimental, and its README lists `print`/`print` as default
credentials. Secure it before exposing it on your network. Using it for Luck
Jingle requires a custom add-on image that includes the backend and queue
configuration; otherwise, use the separate Linux-host setup above.

The integration itself does not install CUPS or advertise the queue. Wherever
CUPS runs, its queue sharing and LAN/mDNS configuration are managed by that
CUPS server.

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
