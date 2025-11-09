"""Constants for Energy Stats integration."""

DOMAIN = "energy_stats"
CONF_DAILY_RESET = "daily_reset_time"

# Die Keys, die im ConfigFlow als auswählbare Sensoren auftauchen
SENSOR_KEYS = {
    "grid_power": ["power", "mandatory"],
    "grid_in_energy": ["energy", "mandatory"],
    "grid_out_energy": ["energy", "optional"],
    "battery_power": ["power", "optional"],
    "battery_energy": ["energy_storage", "optional"],
    "pv_power": ["power", "optional"],
    "pv_energy": ["energy", "optional"],
    "car_charging_power": ["power", "optional"],
    "car_charging_limit_power": ["power", "optional"],
    "car_charging_energy": ["energy", "optional"],
    "car_connected": ["plug", "optional"],
    "car_soc": ["battery", "optional"],
}

CALCULATED_VALUES = {
    "grid_in_energy_daily": ["Daily Imported Energy", "energy", "total", "Wh"],
    "grid_out_energy_daily": ["Daily Fed-In Energy", "energy", "total", "Wh"],
    "pv_energy_daily": ["Daily Generated PV Energy", "energy", "total", "Wh"],
    "home_energy_daily": ["Daily Consumed Home Energy", "energy", "total", "Wh"],
    "car_charging_energy_session": [
        "Energy Current Charging Session",
        "energy",
        "total",
        "Wh",
    ],
    "home_energy_mix_daily": ["Energy Mix Home", None, "measurement", None],
    "battery_energy_mix_daily": ["Energy Mix Battery", None, "measurement", None],
    "car_charging_energy_mix": [
        "Energy Mix Car Charging (last session)",
        None,
        "measurement",
        None,
    ],
}
