"""Constants for the Luck Jingle integration."""

from homeassistant.const import Platform

DOMAIN = "luck_jingle"

CONF_ADDRESS = "address"
CONF_BLUETOOTH_ADAPTER = "bluetooth_adapter"
CONF_ENABLE_NETWORK_PRINT = "enable_network_print"
CONF_MODEL = "model"
CONF_NAME = "name"

BLUETOOTH_ADAPTER_AUTO = "auto"

SERVICE_PRINT_TEXT = "print_text"

PLATFORMS = [Platform.BUTTON, Platform.BINARY_SENSOR]
