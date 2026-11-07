class BridgeError(Exception):
    """Base class for expected bridge errors."""


class ConfigurationError(BridgeError):
    """The user configuration is invalid."""


class HomeAssistantError(BridgeError):
    """Home Assistant could not be queried."""


class KACError(BridgeError):
    """A KAC request failed or was rejected."""


class RenderError(BridgeError):
    """A configured page could not be rendered."""


class ImageError(BridgeError):
    """A configured image could not be prepared or uploaded."""
