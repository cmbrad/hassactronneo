"""Climate platform for Actron Air Neo integration."""

import logging

from typing import Any

from actron_neo_api import ActronNeoAPI

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ActronConfigEntry
from .const import DOMAIN
from .coordinator import ActronNeoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_TEMP_MIN = 16.0
DEFAULT_TEMP_MAX = 32.0
FAN_MODE_MAPPING = {
    "auto": "AUTO",
    "low": "LOW",
    "medium": "MED",
    "high": "HIGH",
}
FAN_MODE_MAPPING_REVERSE = {v: k for k, v in FAN_MODE_MAPPING.items()}
HVAC_MODE_MAPPING = {
    "COOL": HVACMode.COOL,
    "HEAT": HVACMode.HEAT,
    "FAN": HVACMode.FAN_ONLY,
    "AUTO": HVACMode.AUTO,
    "OFF": HVACMode.OFF,
}
HVAC_MODE_MAPPING_REVERSE = {v: k for k, v in HVAC_MODE_MAPPING.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ActronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Actron Air Neo climate entities."""
    # Get the API and coordinator from the integration
    coordinator = entry.runtime_data

    # Add system-wide climate entity
    entities: list[ClimateEntity] = []

    for system in coordinator.api.systems:
        name = system["description"]
        serial_number = system["serial"]
        entities.append(ActronSystemClimate(coordinator, serial_number, name))

        zones = coordinator.data[serial_number].get("RemoteZoneInfo", [])

        zone_map = dict(enumerate(zones, start=0))
        for zone_number, zone in zone_map.items():
            if zone["NV_Exists"]:
                zone_name = zone["NV_Title"]
                entities.append(
                    ActronZoneClimate(
                        coordinator, serial_number, zone_name, zone_number
                    )
                )

    async_add_entities(entities)


class ActronSystemClimate(
    CoordinatorEntity[ActronNeoDataUpdateCoordinator], ClimateEntity
):
    """Representation of the Actron Air Neo system."""

    _attr_has_entity_name = True
    _attr_fan_modes = ["auto", "low", "medium", "high"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: ActronNeoDataUpdateCoordinator,
        serial_number: str,
        name: str,
    ) -> None:
        """Initialize an Actron Air Neo unit."""
        super().__init__(coordinator)
        self._api: ActronNeoAPI = coordinator.api
        self._serial_number: str = serial_number
        self._attr_unique_id: str = self._serial_number
        self._manufacturer: str = "Actron Air"
        self._name: str = name
        self._attr_name: None = None
        self._firmware_version: str = (
            self.coordinator.data[self._serial_number]
            .get("AirconSystem", {})
            .get("MasterWCFirmwareVersion")
        )
        self._model_name: str = (
            self.coordinator.data[self._serial_number]
            .get("AirconSystem", {})
            .get("MasterWCModel")
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            name=self._name,
            manufacturer="Actron Air",
            model=self.coordinator.data[self._serial_number]
            .get("AirconSystem", {})
            .get("MasterWCModel"),
            sw_version=self.coordinator.data[self._serial_number]
            .get("AirconSystem", {})
            .get("MasterWCFirmwareVersion"),
            serial_number=serial_number,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # shared data
        system_state = (
            self.coordinator.data[self._serial_number]
            .get("UserAirconSettings", {})
            .get("isOn")
        )
        defrost = (
            self.coordinator.data[self._serial_number]
            .get("LiveAircon", {})
            .get("Defrost")
        )
        system_mode = (
            self.coordinator.data[self._serial_number]
            .get("UserAirconSettings", {})
            .get("Mode")
        )
        compressor_mode = (
            self.coordinator.data[self._serial_number]
            .get("LiveAircon", {})
            .get("CompressorMode")
        )
        fan_mode = (
            self.coordinator.data[self._serial_number]
            .get("UserAirconSettings", {})
            .get("FanMode")
            .upper()
        )

        _LOGGER.debug(
            "System state: %s, Defrost: %s, System mode: %s, Compressor mode: %s, Fan mode: %s",
            system_state,
            defrost,
            system_mode,
            compressor_mode,
            fan_mode,
        )

        # update hvac mode
        if not system_state:
            hvac_mode = HVACMode.OFF
        else:
            hvac_mode = (
                self.coordinator.data[self._serial_number]
                .get("UserAirconSettings", {})
                .get("Mode")
            )

        self._attr_hvac_mode = HVAC_MODE_MAPPING.get(hvac_mode, HVACMode.OFF)

        # hvac action
        # if system is off then the action is off
        if not system_state:
            hvac_action = HVACAction.OFF
        elif defrost:
            hvac_action = HVACAction.DEFROSTING
        elif system_mode in ["COOL", "AUTO"] and compressor_mode == "COOL":
            hvac_action = HVACAction.COOLING
        elif system_mode in ["HEAT", "AUTO"] and compressor_mode == "HEAT":
            hvac_action = HVACAction.HEATING
        elif system_mode == "FAN" or "CONT" in fan_mode:
            hvac_action = HVACAction.FAN
        else:
            hvac_action = HVACAction.IDLE

        self._attr_hvac_action = hvac_action

        # fan mode
        fan_mode_without_cont = fan_mode.split("+")[0]
        self._attr_fan_mode = FAN_MODE_MAPPING_REVERSE.get(
            fan_mode_without_cont, "AUTO"
        )

        # humidity
        self._attr_current_humidity = (
            self.coordinator.data[self._serial_number]
            .get("MasterInfo", {})
            .get("LiveHumidity_pc")
        )

        # temperature
        self._attr_current_temperature = (
            self.coordinator.data[self._serial_number]
            .get("MasterInfo", {})
            .get("LiveTemp_oC")
        )

        # target temperature
        """Return the target temperature."""
        if system_mode == "HEAT":
            target_temperature = (
                self.coordinator.data[self._serial_number]
                .get("UserAirconSettings", {})
                .get("TemperatureSetpoint_Heat_oC")
            )
        elif system_mode == "FAN":
            target_temperature = None
        else:
            target_temperature = (
                self.coordinator.data[self._serial_number]
                .get("UserAirconSettings", {})
                .get("TemperatureSetpoint_Cool_oC")
            )

        self._attr_target_temperature = target_temperature

        # min temperature
        self._attr_min_temp = (
            self.coordinator.data[self._serial_number]
            .get("NV_Limits", {})
            .get("UserSetpoint_oC", {})
            .get("setCool_Min", 16.0)
        )

        # max temperature
        self._attr_max_temp = (
            self.coordinator.data[self._serial_number]
            .get("NV_Limits", {})
            .get("UserSetpoint_oC", {})
            .get("setCool_Max", 32.0)
        )

        # done
        self.async_write_ha_state()

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return HVAC Modes."""
        return [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.AUTO,
            HVACMode.FAN_ONLY,
        ]

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        api_fan_mode = FAN_MODE_MAPPING.get(fan_mode.lower())
        await self._api.set_fan_mode(self._serial_number, fan_mode=api_fan_mode)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        ac_mode = HVAC_MODE_MAPPING_REVERSE.get(hvac_mode)
        if not ac_mode:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

        if hvac_mode == HVACMode.OFF:
            await self._api.set_system_mode(self._serial_number, is_on=False)
        else:
            await self._api.set_system_mode(
                self._serial_number, is_on=True, mode=ac_mode
            )

        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the temperature."""
        temp = kwargs.get("temperature")
        hvac_mode = self.hvac_mode.lower()

        if hvac_mode == HVACMode.COOL:
            await self._api.set_temperature(
                self._serial_number,
                mode="COOL",
                temperature=temp,
            )
        elif hvac_mode == HVACMode.HEAT:
            await self._api.set_temperature(
                self._serial_number,
                mode="HEAT",
                temperature=temp,
            )
        elif hvac_mode == HVACMode.AUTO:
            mode = "AUTO"
            temp = {"cool": temp, "heat": temp}

        await self._api.set_temperature(
            self._serial_number,
            mode=mode,
            temperature=temp,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on_continuous(self, continuous: bool) -> None:
        """Set the continuous mode."""
        await self._api.set_fan_mode(
            self._serial_number, fan_mode=self._attr_fan_mode, continuous=continuous
        )
        await self.coordinator.async_request_refresh()


class ActronZoneClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a zone within the Actron Air system."""

    _attr_has_entity_name = True
    _attr_fan_modes = ["auto", "low", "medium", "high"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: ActronNeoDataUpdateCoordinator,
        serial_number: str,
        zone_name: str,
        zone_number: int,
    ) -> None:
        """Initialize an Actron Air Neo unit."""
        super().__init__(coordinator)
        self._api: ActronNeoAPI = coordinator.api
        self._serial_number: str = serial_number
        self._name: str = zone_name
        self._zone_number = zone_number
        self._attr_name: None = None
        self._attr_unique_id = f"{self._serial_number}_zone_{self._zone_number}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self._name,
            manufacturer="Actron Air",
            model="Zone",
            suggested_area=self._name,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Zone-specific data
        zone = self.coordinator.data[self._serial_number]["RemoteZoneInfo"][
            self._zone_number
        ]
        enabled_zones = self.coordinator.data[self._serial_number][
            "UserAirconSettings"
        ]["EnabledZones"]
        system_mode = self.coordinator.data[self._serial_number]["UserAirconSettings"][
            "Mode"
        ]
        compressor_mode = self.coordinator.data[self._serial_number]["LiveAircon"][
            "CompressorMode"
        ]
        fan_mode = self.coordinator.data[self._serial_number]["UserAirconSettings"][
            "FanMode"
        ].upper()
        defrost = self.coordinator.data[self._serial_number]["LiveAircon"]["Defrost"]
        system_state = self.coordinator.data[self._serial_number]["UserAirconSettings"][
            "isOn"
        ]

        _LOGGER.debug(
            "Zone %s: %s, System state: %s, Defrost: %s, System mode: %s, Compressor mode: %s, Fan mode: %s",
            self._zone_number,
            enabled_zones[self._zone_number],
            system_state,
            defrost,
            system_mode,
            compressor_mode,
            fan_mode,
        )

        # Update hvac_mode
        if enabled_zones[self._zone_number]:
            self._attr_hvac_mode = HVAC_MODE_MAPPING.get(system_mode, HVACMode.OFF)
        else:
            self._attr_hvac_mode = HVACMode.OFF

        # Update hvac_action
        if not system_state or not enabled_zones[self._zone_number]:
            hvac_action = HVACAction.OFF
        elif defrost:
            hvac_action = HVACAction.DEFROSTING
        elif system_mode in ["COOL", "AUTO"] and compressor_mode == "COOL":
            hvac_action = HVACAction.COOLING
        elif system_mode in ["HEAT", "AUTO"] and compressor_mode == "HEAT":
            hvac_action = HVACAction.HEATING
        elif system_mode == "FAN" or "CONT" in fan_mode:
            hvac_action = HVACAction.FAN
        else:
            hvac_action = HVACAction.IDLE

        self._attr_hvac_action = hvac_action

        # Update current_humidity
        self._attr_current_humidity = zone["LiveHumidity_pc"]

        # Update current_temperature
        self._attr_current_temperature = zone["LiveTemp_oC"]

        # Update target_temperature
        if system_mode == "HEAT":
            self._attr_target_temperature = zone["TemperatureSetpoint_Heat_oC"]
        elif system_mode == "FAN":
            self._attr_target_temperature = None
        else:
            self._attr_target_temperature = zone["TemperatureSetpoint_Cool_oC"]

        # Update min_temp
        min_setpoint = self.coordinator.data[self._serial_number]["NV_Limits"][
            "UserSetpoint_oC"
        ]["setCool_Min"]
        target_setpoint = self.coordinator.data[self._serial_number][
            "UserAirconSettings"
        ]["TemperatureSetpoint_Cool_oC"]
        temp_variance = self.coordinator.data[self._serial_number][
            "UserAirconSettings"
        ]["ZoneTemperatureSetpointVariance_oC"]
        self._attr_min_temp = max(min_setpoint, target_setpoint - temp_variance)

        # Update max_temp
        max_setpoint = self.coordinator.data[self._serial_number]["NV_Limits"][
            "UserSetpoint_oC"
        ]["setCool_Max"]
        self._attr_max_temp = min(max_setpoint, target_setpoint + temp_variance)

        # Done
        self.async_write_ha_state()

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return HVAC Modes."""
        # zones cannot be set to individual modes - their only valid operation is
        # either off, or the same mode as the core system
        hvac_mode = (
            self.coordinator.data[self._serial_number]
            .get("UserAirconSettings", {})
            .get("Mode")
        )
        return [HVACMode.OFF, HVAC_MODE_MAPPING[hvac_mode]]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        is_enabled = hvac_mode != HVACMode.OFF

        await self._api.set_zone(
            serial_number=self._serial_number,
            zone_number=self._zone_number,
            is_enabled=is_enabled,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the temperature."""
        temp = kwargs["temperature"]
        hvac_mode = self.hvac_mode

        if hvac_mode == HVACMode.COOL:
            mode = "COOL"
        elif hvac_mode == HVACMode.HEAT:
            mode = "HEAT"
        elif hvac_mode == HVACMode.AUTO:
            mode = "AUTO"
            temp = {"cool": temp, "heat": temp}

        await self._api.set_temperature(
            serial_number=self._serial_number,
            mode=mode,
            temperature=temp,
            zone=self._zone_number,
        )
        await self.coordinator.async_request_refresh()
