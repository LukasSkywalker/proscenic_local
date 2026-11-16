"""Config flow for Proscenic Local."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_USER_ID,
    DOMAIN,
)


class ProscenicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Proscenic Local."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """First (and only) step: host, device id, local key, protocol."""
        errors = {}
        if user_input is not None:
            errors = await self._test_connection(user_input)
            if not errors:
                return self.async_create_entry(title="M8 Pro", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_LOCAL_KEY): str,
                    vol.Required(CONF_PROTOCOL_VERSION, default="3.3"): vol.In(
                        ["3.1", "3.3", "3.4", "3.5"]
                    ),
                    vol.Optional(CONF_USER_ID, default=""): str,
                }
            ),
            errors=errors,
        )

    async def _test_connection(self, user_input):
        """Open a tinytuya connection and read status. Return a dict of errors."""
        import tinytuya

        try:
            device = tinytuya.Device(
                user_input[CONF_DEVICE_ID],
                user_input[CONF_HOST],
                user_input[CONF_LOCAL_KEY],
                version=float(user_input[CONF_PROTOCOL_VERSION]),
            )
            device.set_socketTimeout(5)
            status = await self.hass.async_add_executor_job(device.status)
        except Exception:
            return {"base": "cannot_connect"}

        if isinstance(status, dict) and "Error" in status:
            return {CONF_LOCAL_KEY: "invalid_auth"}
        return {}
