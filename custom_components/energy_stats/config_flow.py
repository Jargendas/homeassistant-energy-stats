"""Configuration flow for the Energy Stats integration."""

import logging
from datetime import datetime

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_DAILY_RESET, CONF_INITIAL_BATTERY_ENERGY_MIX, DOMAIN, SENSOR_KEYS

_LOGGER = logging.getLogger(__name__)


class EnergyStatsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow class for Energy Stats integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, vol.Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Execute main configuraton step."""
        _LOGGER.debug("Executing async_step_user...")
        errors = {}
        if user_input is not None:
            _LOGGER.debug("Processing user input...")
            data = {k: user_input.get(k) for k in SENSOR_KEYS}

            data[CONF_DAILY_RESET] = user_input.get(CONF_DAILY_RESET)  # type: ignore  # noqa: PGH003
            data[CONF_INITIAL_BATTERY_ENERGY_MIX] = user_input.get(CONF_INITIAL_BATTERY_ENERGY_MIX, 0) / 100

            if self.source == config_entries.SOURCE_RECONFIGURE:
                entry = self._get_reconfigure_entry()
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="Reconfigured!")

            return self.async_create_entry(title="Energy Stats", data=data)

        schema_dict = {}

        entry = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
        defaults = entry.data if entry else {}

        # Daily reset time
        try:
            daily_reset_default = datetime.strptime(  # noqa: DTZ007
                str(defaults.get(CONF_DAILY_RESET, "00:00")), "%H:%M"
            ).time()
        except ValueError:
            try:
                daily_reset_default = datetime.strptime(  # noqa: DTZ007
                    str(defaults.get(CONF_DAILY_RESET, "00:00:00")), "%H:%M:%S"
                ).time()
            except ValueError:
                _LOGGER.exception("Reset time could not be parsed!")
        schema_dict[
            vol.Required(
                CONF_DAILY_RESET,
                default=daily_reset_default.isoformat(),
            )
        ] = selector.TimeSelector()

        for key, params in SENSOR_KEYS.items():
            vol_key = None
            if params[1] == "optional":
                vol_key = vol.Optional(
                    key, description={"suggested_value": defaults.get(key)}
                )
            else:
                vol_key = vol.Required(
                    key, description={"suggested_value": defaults.get(key)}
                )

            schema_dict[vol_key] = selector.selector(
                {
                    "entity": {
                        "filter": {
                            "domain": (
                                "binary_sensor" if (params[0] == "plug") else "sensor"
                            ),
                            "device_class": params[0],
                        }
                    }
                }
            )

            if (key == 'battery_energy'):
                schema_dict[
                    vol.Optional(
                        CONF_INITIAL_BATTERY_ENERGY_MIX,
                        default=defaults.get(CONF_INITIAL_BATTERY_ENERGY_MIX, 0) * 100,
                    )
                ] = selector.NumberSelector(config = selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement='%', mode='slider'))

        data_schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            description_placeholders={},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, vol.Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Run reconfiguration of the integration."""
        _LOGGER.debug("Executing async_step_reconfigure...")
        return await self.async_step_user(user_input)
