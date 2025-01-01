import asyncio
from machine import Pin, PWM, SoftI2C
from time import sleep_ms
import aioble
import bluetooth
import network
import os
import json
import ssd1306


class Buzzer:
    def __init__(self, pin):
        self.pwm = PWM(Pin(pin))
        self.pwm.deinit()

    def beep(self, count=1, frequency=2000, duty=32768, on_time=300, off_time=200):
        for _ in range(count):
            self.pwm.init()
            self.pwm.freq(frequency)
            self.pwm.duty_u16(duty)
            sleep_ms(on_time)
            self.pwm.deinit()
            sleep_ms(off_time)

    def off(self):
        self.pwm.duty_u16(0)
        self.pwm.deinit()


class Led:
    def __init__(self, pin):
        self.pin = Pin(pin, Pin.OUT)
        self.state = False

    def on(self):
        self.state = True
        self.pin.value(self.state)

    def off(self):
        self.state = False
        self.pin.value(self.state)

    def toggle(self):
        self.state = not self.state
        self.pin.value(self.state)


class Utils:
    @staticmethod
    def set_uuid():
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        mac = wlan.config('mac')
        return ''.join([f"{b:02X}" for b in mac])

    @staticmethod
    def encode_utf(data):
        return str(data).encode('utf-8')

    @staticmethod
    def decode_utf(data):
        try:
            return data.decode('utf-8')
        except Exception as e:
            print("Decoding Error:", e)
            return None


class Config:
    def __init__(self):
        self.config_path = 'config.json'
        self.default_config = {"wifi_ssid": "", "wifi_pass": ""}
        self._config = {}
        if not os.path.exists(self.config_path):
            self._create_default_config()
        else:
            self._load_config()

    def _create_default_config(self):
        try:
            with open(self.config_path, 'w') as config_file:
                json.dump(self.default_config, config_file)
            self._config = self.default_config.copy()
        except OSError as e:
            print(f"Failed to create default config: {e}")
            self._config = self.default_config.copy()

    def _load_config(self):
        try:
            with open(self.config_path, 'r') as config_file:
                self._config = json.load(config_file)
        except (ValueError, OSError) as e:
            print(f"Failed to load config: {e}")
            self._config = self.default_config.copy()

    def save_config(self):
        try:
            with open(self.config_path, 'w') as config_file:
                json.dump(self._config, config_file)
        except OSError as e:
            print(f"Failed to save config: {e}")

    def get(self, key, default=None):
        return self._config.get(key, default)

    def set(self, key, value):
        self._config[key] = value
        self.save_config()

    def remove(self, key):
        if key in self._config:
            del self._config[key]
            self.save_config()

    def get_all(self):
        return self._config.copy()


class WiFi:
    def __init__(self, ssid, password, on_state_change=None):
        self.ssid = ssid
        self.password = password
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.connected = False
        self.on_state_change = on_state_change
        self.retry_interval = 5  # Retry every 5 seconds
        self.max_retries = 3     # Max retry attempts before giving up
        self.failure_count = 0
        self.tasks = []
        self.tasks.append(self.grab())

    async def grab(self):
        while True:
            try:
                if not self.ssid:
                    print("Wi-Fi Error: SSID is empty. Please set valid credentials.")
                    if self.on_state_change:
                        self.on_state_change(wifi=False)
                    await asyncio.sleep(self.retry_interval)
                    continue  # Skip to the next iteration

                if self.wlan.isconnected():
                    if not self.connected:
                        print(f"Reconnected to Wi-Fi: {self.ssid}")
                        self.connected = True
                        if self.on_state_change:
                            self.on_state_change(wifi=True)
                    print("Wi-Fi is stable and connected.")
                    await asyncio.sleep(self.retry_interval)
                    continue

                # Explicitly disconnect before reconnecting
                self.wlan.disconnect()
                await asyncio.sleep(1)  # Small delay to ensure proper reset

                print("Attempting to connect to Wi-Fi...")
                self.wlan.connect(self.ssid, self.password)

                for _ in range(10):  # Wait up to 10 seconds for connection
                    if self.wlan.isconnected():
                        self.connected = True
                        print(f"Connected to Wi-Fi: {self.ssid}")
                        self.failure_count = 0  # Reset failure counter
                        if self.on_state_change:
                            self.on_state_change(wifi=True)
                        break
                    await asyncio.sleep(1)

                if not self.wlan.isconnected():
                    self.failure_count += 1
                    self.connected = False
                    print(f"Failed to connect to Wi-Fi. Attempt {self.failure_count}/{self.max_retries}")
                    if self.on_state_change:
                        self.on_state_change(wifi=False)

                    if self.failure_count >= self.max_retries:
                        print("Exceeded maximum retries. Please check your Wi-Fi credentials.")
                        break

            except OSError as e:
                self.connected = False
                print(f"Wi-Fi Error: {e}")
                if self.on_state_change:
                    self.on_state_change(wifi=False)
                await asyncio.sleep(self.retry_interval)

            except asyncio.CancelledError:
                print("Wi-Fi task cancelled.")
                break

            finally:
                await asyncio.sleep(self.retry_interval)

    def update_credentials(self, ssid, password):
        print("Updating Wi-Fi credentials...")
        self.ssid = ssid
        self.password = password
        self.connected = False
        self.wlan.disconnect()
        self.failure_count = 0
        if self.on_state_change:
            self.on_state_change(wifi=False)

    def disconnect(self):
        if self.wlan.isconnected():
            self.wlan.disconnect()
            print("Wi-Fi disconnected.")
            if self.on_state_change:
                self.on_state_change(wifi=False)
        else:
            print("Wi-Fi was not connected.")

    def is_connected(self):
        return self.wlan.isconnected()

    def get_ip(self):
        if self.is_connected():
            return self.wlan.ifconfig()[0]
        return None


class BLE:
    def __init__(self,machine_id, set_bt_status, set_ssid_prop, set_pass_prop, send_msg_prop):
        self.machine_id = machine_id
        self.set_bt_status = set_bt_status
        self.set_ssid_prop = set_ssid_prop
        self.set_pass_prop = set_pass_prop
        self.send_msg_prop = send_msg_prop
        self._ADV_INTERVAL_MS = 250_000
        self.tasks = []

        # BLE UUIDs
        self._BLE_SERVICE_UUID = bluetooth.UUID('05154878-a92f-447f-9056-cfba8eec8b0e')
        self._BLE_WIFI_SSID_UUID = bluetooth.UUID('1dee4fcb-7ac0-4520-81de-9cbbff27af73')
        self._BLE_WIFI_PASS_UUID = bluetooth.UUID('4273c7a7-6605-4d55-8ab0-79e114c09baa')
        self._BLE_CONN_STAT_UUID = bluetooth.UUID('db27e855-4588-4a31-a76d-20e7d3bf0ed9')
        self._BLE_MSG_IN_UUID = bluetooth.UUID('0e29a826-7389-4aaa-9aa3-bccb80e34c86')
        self._BLE_MSG_OUT_UUID = bluetooth.UUID('ac7793c6-3a8d-4726-9f26-c8a7e8ee934b')
        self._BLE_MACHINE_ID_UUID = bluetooth.UUID('4df4e89c-c438-4052-9cbe-4cf42529fab1')

        # BLE Service & Characteristics
        self.ble_service = aioble.Service(self._BLE_SERVICE_UUID)
        self.wifi_ssid_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_WIFI_SSID_UUID, read=True, write=True,
            capture=True, notify=True, indicate=True, initial=""
        )
        self.wifi_pass_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_WIFI_PASS_UUID, read=True, write=True,
            capture=True, notify=True, indicate=True, initial=""
        )
        self.conn_stat_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_CONN_STAT_UUID, read=True, notify=True, indicate=True
        )
        self.msg_in_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_MSG_IN_UUID, read=True, indicate=True, notify=True
        )
        self.msg_out_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_MSG_OUT_UUID, read=True, write=True,
            capture=True, notify=True
        )
        self.machine_id_characteristic = aioble.Characteristic(
            self.ble_service, self._BLE_MACHINE_ID_UUID, read=True,
            indicate=True, notify=True, initial=self.machine_id
        )

        aioble.register_services(self.ble_service)
        self.tasks.append(self.advertise())
        self.tasks.append(self.observe_characteristic(self.wifi_ssid_characteristic, self.set_ssid_prop))
        self.tasks.append(self.observe_characteristic(self.wifi_pass_characteristic,self.set_pass_prop))
        self.tasks.append(self.observe_characteristic(self.msg_out_characteristic, self.send_msg_prop))

        

    async def advertise(self):
        while True:
            try:
                async with await aioble.advertise(
                    self._ADV_INTERVAL_MS, name=self.machine_id, services=[self._BLE_SERVICE_UUID]
                ) as connection:
                    try:
                        print("BT Client Connected")
                        self.set_bt_status(bt=True)
                        await connection.disconnected()  # Wait for the disconnection event
                    except Exception as e:
                        print(f"Error during BLE connection: {e}")
                    finally:
                        print("BT Client Disconnected.")
                        self.set_bt_status(bt=False)
            except asyncio.CancelledError:
                print("BLE Terminated")
                break
            except Exception as e:
                print("BLE Error:", e)
            finally:
                await asyncio.sleep_ms(100)

    async def observe_characteristic(self, characteristic, prop_setter):
        while True:
            try:
                connection, data = await characteristic.written()
                if data:
                    decoded_data = Utils.decode_utf(data)
                    print(decoded_data)
                    prop_setter(decoded_data)
            except asyncio.CancelledError:
                print(f"Char Observer task cancelled")
                break
            except Exception as e:
                print(f"Error in Char Observer task:", e)
            finally:
                await asyncio.sleep_ms(100)

class Display:
    def __init__(self, i2c, oled_width, oled_height, machine_id, get_mchine_status):
        self.i2c = i2c
        self.machine_id = machine_id
        self.oled = ssd1306.SSD1306_I2C(oled_width, oled_height, i2c)
        self.get_machine_status = get_mchine_status
        self.tasks = []
        self.tasks.append(self.update())
        
    async def update(self):
        while True:
            try:
                bt = self.get_machine_status("BT")
                wifi = self.get_machine_status("WIFI")
                online = self.get_machine_status("ONLINE")
                mqtt = self.get_machine_status("MQTT")
                self.oled.fill(0)
                self.oled.text("ID:" + self.machine_id, 0, 0)
                self.oled.text("----------------", 0, 9)
                self.oled.text("----------------", 0, 36)
                self.oled.text(f"Wifi:{'OK' if wifi else ' ?'} | BLE:{'OK' if bt else ' ?'}", 0, 45)
                self.oled.text(f"MQTT:{'OK' if mqtt else ' ?'} | NET:{'OK' if online else ' ?'}", 0, 54)
                self.oled.show()
            except asyncio.CancelledError:
                print("Display task cancelled")
                break
            except Exception as e:
                print(f"Error in Display task:", e)
            finally:
                await asyncio.sleep_ms(2000)

        
class EnigmaMachine:
    def __init__(self):
        self.boardLed = Led(2)
        self.buzzer = Buzzer(18)
        self.i2C = SoftI2C(scl=Pin(22), sda=Pin(21))

        self.config = Config()

        self.emMachineID = Utils.set_uuid()
        self.emWifiSSID = self.config.get("wifi_ssid")
        self.emWifiPass = self.config.get("wifi_pass")
        self.emWifiStat = False
        self.emBTStat = False
        self.emOnlineStat = False
        self.emMQTTStat = False
        
        self.ble = BLE(self.emMachineID, self.set_status_cb, self.set_wifi_ssid_cb, self.set_wifi_pass_cb, self.send_msg_cb)
        self.wifi = WiFi(self.emWifiSSID, self.emWifiPass, self.set_status_cb)
        self.display = Display(self.i2C, 128, 64, self.emMachineID, self.get_status_cb)
        
        self.task_list = []
        
    def add_tasks(self, tasks):
        if isinstance(tasks, list):
            self.task_list.extend(tasks)
        else:
            self.task_list.append(tasks)
            
            
    def set_wifi_ssid_cb(self, ssid = None):
        if ssid is not None:
            self.config.set("wifi_ssid", ssid)
            self.emWifiSSID = ssid
            self.config.set("wifi_pass", "")
            self.emWifiPass = ""
            
        self.wifi.update_credentials(self.emWifiSSID, self.emWifiPass)
        print("Wi-Fi SSID updated via BLE.")
        
            
    def set_wifi_pass_cb(self, password = None):
        if password is not None:
            self.config.set("wifi_pass", password)
            self.emWifiPass = password
            
        self.wifi.update_credentials(self.emWifiSSID, self.emWifiPass)
        print("Wi-Fi Password updated via BLE.")
        

    def send_msg_cb(self, msg = None):
        if msg is not None:
            print("New Mesage" , msg)
            
    def set_status_cb(self, bt=None, wifi=None, online=None, mqtt=None):
        if bt is not None:
            self.emBTStat = bt
            print(f"EnigmaMachine Bluetooth State Updated: {self.emBTStat}")
        
        if wifi is not None:
            self.emWifiStat = wifi
            print(f"EnigmaMachine Wi-Fi State Updated: {self.emWifiStat}")
        
        if online is not None:
            self.emOnlineStat = online
            print(f"EnigmaMachine Online State Updated: {self.emOnlineStat}")
        
        if mqtt is not None:
            self.emMQTTStat = mqtt
            print(f"EnigmaMachine MQTT State Updated: {self.emMQTTStat}")
            
    
    def get_status_cb(self, instance):
        status_mapping = {
            'BT': self.emBTStat,
            'WIFI': self.emWifiStat,
            'ONLINE': self.emOnlineStat,
            'MQTT': self.emMQTTStat
        }
        
        # Validate instance
        if instance in status_mapping:
            return status_mapping[instance]
        else:
            raise ValueError("Invalid instance. Allowed values are: 'BT', 'WIFI', 'ONLINE', 'MQTT'")

    
    async def run_tasks(self):
        try:
            await asyncio.gather(*self.task_list)
        except asyncio.CancelledError:
            print("Tasks were cancelled")
        except Exception as e:
            print("Error running tasks:", e)

