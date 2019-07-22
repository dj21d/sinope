"""
Support for Neviweb thermostat.
type 10 = thermostat TH1120RF 3000W and 4000W
type 20 = thermostat TH1300RF 3600W floor, TH1500RF double pole thermostat
type 21 = thermostat TH1400RF low voltage
For more details about this platform, please refer to the documentation at  
https://www.sinopetech.com/en/support/#api
"""
import logging

import voluptuous as vol
import time

import custom_components.neviweb as neviweb
from . import (SCAN_INTERVAL)
from homeassistant.components.climate import (ClimateDevice, ATTR_ENTITY_ID, ATTR_TEMPERATURE,
    ATTR_PRESET_MODE, ATTR_HVAC_MODE, ATTR_HVAC_MODES, ATTR_HVAC_ACTIONS, ATTR_CURRENT_TEMPERATURE)
from homeassistant.components.climate.const import (CURRENT_HVAC_HEAT, 
    CURRENT_HVAC_IDLE, HVAC_MODE_AUTO, HVAC_MODE_OFF, SUPPORT_TARGET_TEMPERATURE,
    HVAC_MODE_HEAT, SUPPORT_PRESET_MODE)
from homeassistant.const import (TEMP_CELSIUS, TEMP_FAHRENHEIT, STATE_OFF)
from datetime import timedelta
from homeassistant.helpers.event import track_time_interval

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE)

DEFAULT_NAME = "neviweb climate"

PRESET_STANDBY = 'bypass'
PRESET_AWAY = 'away'
PRESET_MANUAL = 'manual'
NEVIWEB_STATE_AWAY = 5
NEVIWEB_STATE_OFF = 0
NEVIWEB_TO_HA_PRESET = {
    0: STATE_OFF,
    2: SPRESET_MANUAL,
    3: HVAC_MODE_AUTO,
    5: PRESET_AWAY,
    129: PRESET_STANDBY,
    131: PRESET_STANDBY,
    133: PRESET_STANDBY
}
HA_TO_NEVIWEB_STATE = {
    value: key for key, value in NEVIWEB_TO_HA_PRESET.items()
}
OPERATION_LIST = [STATE_OFF, PRESET_MANUAL, HVAC_MODE_AUTO, PRESET_AWAY, PRESET_STANDBY]

IMPLEMENTED_DEVICE_TYPES = [10, 20, 21]

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the neviweb thermostats."""
    data = hass.data[neviweb.DATA_DOMAIN]
    
    devices = []
    for device_info in data.neviweb_client.gateway_data:
        if device_info["type"] in IMPLEMENTED_DEVICE_TYPES:
            device_name = "{} {}".format(DEFAULT_NAME, device_info["name"])
            devices.append(NeviwebThermostat(data, device_info, device_name))

    add_devices(devices, True)

class NeviwebThermostat(ClimateDevice):
    """Implementation of a Neviweb thermostat."""

    def __init__(self, data, device_info, name):
        """Initialize."""
        self._name = name
        self._client = data.neviweb_client
        self._id = device_info["id"]
        self._wattage = device_info["wattage"]
        self._wattage_override = device_info["wattageOverride"]
        self._min_temp = device_info["tempMin"]
        self._max_temp = device_info["tempMax"]
        self._target_temp = None
        self._cur_temp = None
        self._rssi = None
        self._alarm = None
        self._hvac_mode = None
        self._heat_level = None
        self._is_away = False
        _LOGGER.debug("Setting up %s: %s", self._name, device_info)

    def update(self):
        """Get the latest data from Neviweb and update the state."""
        start = time.time()
        device_data = self._client.get_device_data(self._id)
        end = time.time()
        elapsed = round(end - start, 3)
        _LOGGER.debug("Updating %s (%s sec): %s",
        self._name, elapsed, device_data)

        if "errorCode" in device_data:
            if device_data["errorCode"] == None:
                self._cur_temp = float(device_data["temperature"])
                self._target_temp = float(device_data["setpoint"]) if \
                    device_data["setpoint"] is not None else 0.0
                self._heat_level = device_data["heatLevel"] if \
                    device_data["heatLevel"] is not None else 0
                self._alarm = device_data["alarm"]
                self._rssi = device_data["rssi"]
                self._hvac_mode = device_data["mode"] if \
                    device_data["mode"] is not None else 2
                if device_data["mode"] != NEVIWEB_STATE_AWAY:
                    self._is_away = False
                else:
                    self._is_away = True
                return
        elif "code" in device_data:
            _LOGGER.warning("Error while updating %s. %s: %s", self._name,
                device_data["code"], device_data["message"])
        else:
            _LOGGER.warning("Cannot update %s: %s", self._name, device_data)

    @property
    def unique_id(self):
        """Return unique ID based on Neviweb device ID."""
        return self._id

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def state(self):
        """Return current state i.e. heat, off, idle."""
        if self._hvac_mode != HVAC_MODE_OFF:
            return HVAC_MODE_HEAT
        if self._hvac_mode == NEVIWEB_STATE_OFF:
            return HVAC_MODE_OFF
        return CURRENT_HVAC_IDLE #STATE_IDLE

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {'alarm': self._alarm,
                'heat_level': self._heat_level,
                'rssi': self._rssi,
                'wattage': self._wattage,
                'wattage_override': self._wattage_override,
                'id': self._id}

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS

    @property
    def min_temp(self):
        """Return the min temperature."""
        return self._min_temp

    @property
    def max_temp(self):
        """Return the max temperature."""
        return self._max_temp

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_operation(self):
        """Return current operation i.e. off, auto, manual."""
        return self.to_hass_operation_mode(self._hvac_mode)

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return PRESET_LIST

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self.to_hass_operation_mode(self._hvac_mode)

    @property
    def preset_modes(self):
        """Return the list of available operation modes."""
        return PRESET_LIST

    @property
    def preset_mode(self):
        """Return current preset mode."""
        modes = self.to_hass_operation_mode(self._hvac_mode)
        for mode in modes: 
        
            if mode == HVAC_MODE_AUTO:
                return HVAC_MODE_AUTO
        
            if mode == STATE_OFF:
                return STATE_OFF

            if mode == PRESET_MANUAL:
                return PRESET_MANUAL

            if mode == PRESET_AWAY:
                return PRESET_AWAY

            if mode == PRESET_STANDBY:
                return PRESET_STANDBY
    
        return None

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._cur_temp
    
    @property
    def target_temperature (self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def is_away_mode_on(self):
        return self._is_away

 #   @property
 #   def is_on(self):
 #       if self._heat_level == None:
 #           self._heat_level = 0
 #       return self._heat_level > 0

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._client.set_temperature(self._id, temperature)
        self._target_temp = temperature

    def set_hvac_mode(self, hvac_mode):
        """Set new operation mode."""
        mode = self.to_neviweb_hvac_mode(hvac_mode)
        self._client.set_mode(self._id, mode)

    def to_neviweb_hvac_mode(self, mode):
        """Translate hass operation modes to neviweb modes."""
        if mode in HA_TO_NEVIWEB_STATE:
            return HA_TO_NEVIWEB_STATE[mode]
        _LOGGER.error("Operation mode %s could not be mapped to neviweb", mode)
        return None
        
    def to_hass_operation_mode(self, mode):
        """Translate neviweb operation modes to hass operation modes."""
        if mode in NEVIWEB_TO_HA_PRESET:
            return NEVIWEB_TO_HA_PRESET[mode]
        _LOGGER.error("Operation mode %s could not be mapped to hass", mode)
        return None
    
    def set_preset(self,preset):
        """change preset mode."""
        
        if preset == self.preset_mode:
            return

        if preset == STATE_OFF:
            self._client.set_mode(self._id, STATE_OFF)
            return "off"

        if preset == NEVIWEB_STATE_AWAY:
            self._client.set_mode(self._id, NEVIWEB_STATE_AWAY)
            return "away"

        if preset == PRESET_STANDBY:
            self._client.set_mode(self._id, PRESET_STANDBY)
            return "bypass"

        if preset == PRESET_MANUAL:
            self._client.set_mode(self._id, PRESET_MANUAL)
            return "manual"

        if preset == HVAC_MODE_AUTO:
            self._client.set_mode(self._id, HVAC_MODE_AUTO)
            return "auto" 

    def turn_away_mode_off(self):
        """Turn away mode off."""
        if self._hvac_mode >= 129:
            self._hvac_mode = 3 
        self._client.set_mode(self._id, self._hvac_mode)
        self._is_away = False
        
    def turn_off(self):
        """Turn device off."""
        self._client.set_mode(self._id, NEVIWEB_STATE_OFF)

    def turn_on(self):
        """Turn device on (auto mode)."""
        self._client.set_mode(self._id, 3)
