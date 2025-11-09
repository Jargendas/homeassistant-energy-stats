"""Energy Stats coordinator integration."""

import logging
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_DAILY_RESET, SENSOR_KEYS

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "energy_stats_data"


class EnergyStatsCoordinator(DataUpdateCoordinator):
    """Coordinator class for the module."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator with provided config entry."""
        self.entry = entry
        self.hass = hass
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Energy Stats",
            update_interval=timedelta(seconds=5),
            config_entry=entry,
        )
        self.entry_id = entry.entry_id
        self.sensors = {k: entry.data.get(k) for k in SENSOR_KEYS}

        try:
            self.daily_reset = datetime.strptime(  # noqa: DTZ007
                str(entry.data.get(CONF_DAILY_RESET, "00:00")), "%H:%M"
            ).time()
        except ValueError:
            try:
                self.daily_reset = datetime.strptime(  # noqa: DTZ007
                    str(entry.data.get(CONF_DAILY_RESET, "00:00:00")), "%H:%M:%S"
                ).time()
            except ValueError:
                _LOGGER.exception("Reset time could not be parsed!")

        _LOGGER.debug("Initialized daily_reset type:")
        _LOGGER.debug(str(self.daily_reset))
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")

        self._last_update = datetime.now(UTC)
        self._energy_sums = {}  # Daily cumulated energies
        self._last_reset = datetime.now(UTC)
        self._energy_baselines = {}  # Daily baseline to calculate daily energies from total energy sensor # noqa: E501
        self._pv_sums = {}  # Cumulated consumed PV energy for all consumers for energy mix calculation  # noqa: E501
        self._grid_sums = {}  # Cumulated consumed grid energy for all consumers for energy mix calculation  # noqa: E501

        _LOGGER.info("Update interval is %s", self.update_interval)

    async def _async_update_data(self) -> dict[str, float | bool | list[str]]:  # noqa: C901, PLR0912, PLR0915
        _LOGGER.debug("Executing _async_update_data")

        if not self._energy_sums:
            stored = await self._store.async_load()
            if stored:
                self._energy_sums = stored.get("energy_sums", {}) or {}
                self._energy_baselines = stored.get("energy_baselines", {}) or {}
                self._pv_sums = stored.get("pv_sums", {}) or {}
                self._grid_sums = stored.get("grid_sums", {}) or {}
                self._last_reset = datetime.fromisoformat(stored.get("last_reset"))
            else:
                self._energy_sums = {}
                self._energy_baselines = {}
                self._pv_sums = {}
                self._grid_sums = {}
                self._last_reset = datetime.now(UTC)

        now = datetime.now(UTC)
        elapsed_h = (
            (now - self._last_update).total_seconds() / 3600.0
            if self._last_update
            else 0
        )
        self._last_update = now

        state = self.hass.states

        result = {}
        self._calculated_keys = []

        def get_value(entity_id: str) -> float | bool | None:
            if not entity_id:
                return None
            st = state.get(entity_id)
            if not st or st.state in ("unknown", "unavailable", None):
                return None
            try:
                val = float(st.state)

                unit = st.attributes.get("unit_of_measurement")
                if unit:
                    unit = unit.lower()
                    if unit in ("kw", "kwatt", "kilowatt"):
                        val = val * 1000  # → W
                    if unit in ("kwh", "kwhours", "kilowatt-hour", "kilowatt hour"):
                        val = val * 1000  # → Wh

                return val  # noqa: TRY300

            except (ValueError, TypeError):
                if st.state == "on":
                    return True
                if st.state == "off":
                    return False
                return None

        # Get raw values
        raw_vals = {}
        for key in SENSOR_KEYS:
            entity_id = self.sensors.get(key)
            if entity_id is not None:
                value = get_value(entity_id)
                if value is None:
                    errmsg = f"Entity {entity_id} is not ready!"
                    _LOGGER.debug(errmsg)
                    raise UpdateFailed(errmsg)
                raw_vals[key] = value
                _LOGGER.debug("Value for %s: %s", key, str(raw_vals[key]))
            else:
                _LOGGER.debug("No Entity found for %s", key)
                raw_vals[key] = None

        # Momentary powers
        if raw_vals["grid_power"] is not None:
            result["grid_power"] = raw_vals["grid_power"]

        if raw_vals["car_charging_power"] is not None:
            result["car_charging_power"] = raw_vals["car_charging_power"]

        if raw_vals["car_charging_limit_power"] is not None:
            result["car_charging_limit_power"] = raw_vals["car_charging_limit_power"]

        if raw_vals["pv_power"] is not None:
            result["pv_power"] = raw_vals["pv_power"]

        if raw_vals["battery_power"] is not None:
            result["battery_power"] = raw_vals["battery_power"]

        if raw_vals["car_connected"] is not None:
            result["car_connected"] = int(raw_vals["car_connected"])

        if raw_vals["car_soc"] is not None:
            result["car_soc"] = raw_vals["car_soc"]

        self._update_energy(
            "grid_in_energy_daily",
            raw_vals["grid_in_energy"],
            raw_vals["grid_power"],
            elapsed_h,
        )
        self._update_energy(
            "grid_out_energy_daily",
            raw_vals["grid_out_energy"],
            -raw_vals["grid_power"] if raw_vals["grid_power"] is not None else None,
            elapsed_h,
        )
        self._update_energy(
            "pv_energy_daily", raw_vals["pv_energy"], raw_vals["pv_power"], elapsed_h
        )
        self._update_energy(
            "car_charging_energy",
            raw_vals["car_charging_energy"],
            raw_vals["car_charging_power"],
            elapsed_h,
            use_baseline=False,
        )

        if raw_vals["battery_energy"] is not None:
            self._energy_sums["battery_energy"] = raw_vals["battery_energy"]

        grid_in = self._energy_sums.get("grid_in_energy")
        grid_out = self._energy_sums.get("grid_out_energy", 0.0)
        pv_e = self._energy_sums.get("pv_energy")
        if grid_in is not None and pv_e is not None:
            home_energy = grid_in + pv_e - grid_out
            self._energy_sums["home_energy_daily"] = home_energy

        result.update(dict(self._energy_sums.items()))

        def _mix_ratio(key: str) -> float:
            pv_sum = self._pv_sums.get(key, 0.0)
            grid_sum = self._grid_sums.get(key, 0.0)
            total = pv_sum + grid_sum
            return pv_sum / total if total > 0 else 0

        # --- Energy Mixes ---
        if raw_vals["battery_power"] and raw_vals["battery_power"] > 0:
            self._add_mix_energy(
                "battery_power",
                raw_vals["pv_power"],
                raw_vals["grid_power"],
                elapsed_h,
            )
            result["battery_energy_mix_daily"] = _mix_ratio("battery_energy")
            self._calculated_keys.append("battery_energy_mix_daily")

        self._add_mix_energy(
            "home_energy_daily",
            raw_vals["pv_power"],
            raw_vals["grid_power"],
            elapsed_h,
            result.get("battery_power"),
            result.get("battery_energy_mix_daily"),
        )
        result["home_energy_mix_daily"] = _mix_ratio("home_energy_daily")
        self._calculated_keys.append("home_energy_mix_daily")

        if raw_vals["car_charging_power"] is not None:
            self._add_mix_energy(
                "car_charging_energy",
                raw_vals["pv_power"],
                raw_vals["grid_power"],
                elapsed_h,
                result.get("battery_power"),
                result.get("battery_energy_mix_daily"),
            )
            result["car_charging_energy_mix"] = _mix_ratio("car_charging_energy")
            self._calculated_keys.append("car_charging_energy_mix")

        # Daily reset
        local_tz = dt_util.DEFAULT_TIME_ZONE
        reset_time_utc = (
            datetime.combine(dt_util.now(time_zone=local_tz).date(), self.daily_reset)
            .replace(tzinfo=local_tz)
            .astimezone(UTC)
        )

        _LOGGER.debug("Planned reset time (UTC): %s", str(reset_time_utc))
        _LOGGER.debug("Current time (UTC): %s", str(now))
        if now >= reset_time_utc and self._last_reset < reset_time_utc:
            _LOGGER.info("Energy Stats: Resetting daily values to 0.")
            self._energy_sums = {}
            self._energy_baselines = {}
            self._pv_sums = {}
            self._grid_sums = {}
            self._last_reset = now

        result["calculated_keys"] = self._calculated_keys

        try:
            await self._store.async_save(
                {
                    "energy_sums": self._energy_sums,
                    "pv_sums": self._pv_sums,
                    "grid_sums": self._grid_sums,
                    "energy_baselines": self._energy_baselines,
                    "last_reset": self._last_reset.isoformat(),
                }
            )
        except Exception:
            _LOGGER.exception("Error while saving stats")

        _LOGGER.debug("Done running update: %s ", str(result))

        return result

    def _update_energy(
        self,
        key: str,
        energy_sensor_value: float | None,
        power_sensor_value: float | None,
        elapsed_h: float,
        *,
        use_baseline: bool = True,
    ) -> None:
        """Update daily energy values, either by using the energy sensor or by integrating the power sensor value."""  # noqa: E501
        if energy_sensor_value is not None:
            baseline = 0
            if use_baseline:
                baseline = self._energy_baselines.get(key)
                if baseline is None:
                    self._energy_baselines[key] = energy_sensor_value
                    baseline = energy_sensor_value
                self._calculated_keys.append(key)
            self._energy_sums[key] = max(0.0, energy_sensor_value - baseline)
            return

        if power_sensor_value is not None and elapsed_h > 0 and power_sensor_value > 0:
            prev = self._energy_sums.get(key, 0.0)
            self._energy_sums[key] = prev + (power_sensor_value / 1000.0) * elapsed_h
            self._calculated_keys.append(key)

    def _add_mix_energy(  # noqa: PLR0913
        self,
        key: str,
        pv_power: float | None,
        grid_power: float | None,
        elapsed_h: float,
        battery_power: float | None = None,
        battery_pv_factor: float | None = None,
    ) -> None:
        """Accumulate consumed PV and grid energies."""
        if pv_power is None:
            pv_power = 0
        if grid_power is None:
            grid_power = 0
            return

        if battery_power is not None and battery_power > 0:
            if battery_pv_factor is not None:
                grid_power += (1 - battery_pv_factor) * battery_power
                pv_power += battery_pv_factor * battery_power
            else:
                grid_power += battery_power

        pv_part = max(0.0, pv_power) * elapsed_h
        grid_part = max(0.0, grid_power) * elapsed_h
        self._pv_sums[key] = self._pv_sums.get(key, 0.0) + pv_part
        self._grid_sums[key] = self._grid_sums.get(key, 0.0) + grid_part

        _LOGGER.debug("%s: %f, %f", key, self._pv_sums[key], self._grid_sums[key])
