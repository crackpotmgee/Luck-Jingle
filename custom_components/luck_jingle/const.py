"""Constants for the Luck Jingle integration."""

from homeassistant.const import Platform

DOMAIN = "luck_jingle"

CONF_ADDRESS = "address"
CONF_NAME = "name"

DEFAULT_NAME = "Luck Jingle Printer"

SERVICE_PRINT_TEXT = "print_text"

PLATFORMS = [Platform.BUTTON]
