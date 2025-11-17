#!/usr/bin/env python3
import os
import time
import ssl
import logging
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

import psutil
import paho.mqtt.client as mqtt
from influxdb_client_3 import InfluxDBClient3, Point

try:
    import RPi.GPIO as GPIO
except (RuntimeError, ImportError):
    print("WARNING: RPi.GPIO not available.")
    GPIO = None

try:
    import adafruit_dht
    import board
except ImportError:
    print("WARNING: adafruit-circuitpython-dht not available. DHT11 sensor will be disabled.")
    adafruit_dht = None
    board = None

# --- Ultrasonic HC-SR04 setup ---
class HCSR04:
    def __init__(self, trig_pin, echo_pin):
        if not GPIO:
            raise RuntimeError("RPi.GPIO is required for HC-SR04")
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.trig_pin, GPIO.OUT)
        GPIO.setup(self.echo_pin, GPIO.IN)

    def distance_cm(self):
        # send pulse
        GPIO.output(self.trig_pin, True)
        time.sleep(0.00001)
        GPIO.output(self.trig_pin, False)
        start_time = time.time()
        stop_time = time.time()

        # save start
        while GPIO.input(self.echo_pin) == 0:
            start_time = time.time()
        while GPIO.input(self.echo_pin) == 1:
            stop_time = time.time()
        elapsed = stop_time - start_time
        distance = (elapsed * 34300) / 2  # cm
        return round(distance, 1)

DEVICE_NAME = socket.gethostname()

MQTT_BROKER = "t0761115.ala.eu-central-1.emqxsl.com"
MQTT_PORT = 8883
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")
CA_CERT = "./server-ca.crt"

TOPICS = {
    "dht11": f"{DEVICE_NAME}/dht11",
    "metrics": f"{DEVICE_NAME}/metrics",
    "ultrasonic": f"{DEVICE_NAME}/ultrasonic"
}

INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN")
INFLUX_ORG = "Mobile and Wireless Networks"
INFLUX_HOST = "https://eu-central-1-1.aws.cloud2.influxdata.com"
INFLUX_BUCKET_SENSOR = "sensor"
INFLUX_BUCKET_METRICS = "metrics"

SENSOR_INTERVAL = 10
METRICS_INTERVAL = 60
ULTRASONIC_INTERVAL = 15  # publish every 15 seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

influx_client = InfluxDBClient3(host=INFLUX_HOST, token=INFLUX_TOKEN, org=INFLUX_ORG)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.value == 0:
        logger.info(f"Connected to MQTT Broker {MQTT_BROKER}")
    else:
        logger.error(f"Failed to connect, return code {reason_code.value}")

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_NAME)
mqtt_client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.on_connect = on_connect
mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
mqtt_client.loop_start()

# --- DHT11 setup ---
dht_device = None
if adafruit_dht and board:
    try:
        dht_device = adafruit_dht.DHT11(board.D4)
    except Exception as e:
        logger.error(f"Failed to initialize DHT11 sensor: {e}")
        dht_device = None

# --- Ultrasonic setup ---
ultrasonic_sensor = None
if GPIO:
    try:
        ultrasonic_sensor = HCSR04(trig_pin=23, echo_pin=24)  # adjust pins as needed
        logger.info("HC-SR04 ultrasonic sensor initialized")
    except Exception as e:
        logger.error(f"Failed to initialize HC-SR04: {e}")
        ultrasonic_sensor = None

def read_dht11():
    if not dht_device:
        logger.warning("DHT11 sensor not initialized or unavailable")
        return None
    try:
        temperature_c = dht_device.temperature
        humidity = dht_device.humidity
        if humidity is not None and temperature_c is not None:
            data = {
                "measurement": "sensor",
                "fields": {"temperature": round(temperature_c, 1), "humidity": round(humidity, 1)},
                "tags": {"device": DEVICE_NAME}
            }
            logger.info(f"DHT11 read → Temp: {data['fields']['temperature']} °C, Humidity: {data['fields']['humidity']}%")
            return data
        else:
            logger.warning("DHT11 read returned None for temperature or humidity")
            return None
    except RuntimeError as error:
        logger.warning(f"DHT11 read error: {error.args[0]}")
        return None


def read_ultrasonic():
    if not ultrasonic_sensor:
        return None
    try:
        distance = ultrasonic_sensor.distance_cm()
        logger.info(f"Ultrasonic distance: {distance} cm")
        return {
            "measurement": "ultrasonic",
            "fields": {"distance_cm": distance},
            "tags": {"device": DEVICE_NAME}
        }
    except Exception as e:
        logger.error(f"Ultrasonic read error: {e}")
        return None

def read_pi_metrics():
    fields = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            fields["pi_temp_c"] = round(float(f.read().strip()) / 1000, 1)
    except Exception:
        fields["pi_temp_c"] = None

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    fields["ram_total_mb"] = round(mem.total / (1024 * 1024), 2)
    fields["ram_used_mb"] = round(mem.used / (1024 * 1024), 2)
    fields["ram_percent"] = mem.percent
    fields["swap_total_mb"] = round(swap.total / (1024 * 1024), 2)
    fields["swap_used_mb"] = round(swap.used / (1024 * 1024), 2)
    fields["swap_percent"] = swap.percent

    disk = psutil.disk_usage('/')
    fields["disk_total_gb"] = round(disk.total / (1024 * 1024 * 1024), 2)
    fields["disk_used_gb"] = round(disk.used / (1024 * 1024 * 1024), 2)
    fields["disk_percent"] = disk.percent

    fields["cpu_percent"] = psutil.cpu_percent(interval=None)
    try:
        cpu_freq = psutil.cpu_freq()
        fields["cpu_freq_mhz"] = round(cpu_freq.current, 2) if cpu_freq else None
    except Exception:
        fields["cpu_freq_mhz"] = None

    per_cpu_list = psutil.cpu_percent(interval=None, percpu=True)
    for i, cpu_usage in enumerate(per_cpu_list):
        fields[f"cpu_core_{i}_percent"] = cpu_usage

    load_avg = os.getloadavg()
    fields["load_avg_1m"] = load_avg[0]
    fields["load_avg_5m"] = load_avg[1]
    fields["load_avg_15m"] = load_avg[2]

    net_io_dict = psutil.net_io_counters()._asdict()
    for key, value in net_io_dict.items():
        fields[f"net_{key}"] = value

    fields["uptime_seconds"] = round(time.time() - psutil.boot_time())
    fields["process_count"] = len(psutil.pids())

    return {
        "measurement": "metrics",
        "fields": fields,
        "tags": {"device": DEVICE_NAME}
    }

def publish_data(payload, bucket, topic):
    timestamp = datetime.now(ZoneInfo("Europe/Skopje"))
    try:
        point = Point(payload["measurement"]).time(timestamp)
        for k, v in payload["fields"].items():
            if v is not None: point.field(k, v)
        for tag, val in payload.get("tags", {}).items():
            point.tag(tag, val)
        influx_client.write(record=point, database=bucket)
        logger.info(f"InfluxDB Published → {bucket}: {payload['measurement']}")
    except Exception as e:
        logger.error(f"Influx write error: {e}")
    try:
        mqtt_payload = payload.copy()
        mqtt_payload['fields']['timestamp'] = timestamp.isoformat()
        mqtt_client.publish(topic, str(mqtt_payload))
        logger.info(f"MQTT Published → {topic}")
    except Exception as e:
        logger.error(f"MQTT publish error: {e}")

if __name__ == "__main__":
    last_sensor_time = 0
    last_metrics_time = 0
    last_ultrasonic_time = 0
    try:
        while True:
            now = time.time()
            if now - last_sensor_time >= SENSOR_INTERVAL:
                last_sensor_time = now
                dht_data = read_dht11()
                if dht_data:
                    publish_data(dht_data, INFLUX_BUCKET_SENSOR, TOPICS["dht11"])

            if now - last_metrics_time >= METRICS_INTERVAL:
                last_metrics_time = now
                metrics_data = read_pi_metrics()
                if metrics_data:
                    publish_data(metrics_data, INFLUX_BUCKET_METRICS, TOPICS["metrics"])

            if now - last_ultrasonic_time >= ULTRASONIC_INTERVAL:
                last_ultrasonic_time = now
                ultrasonic_data = read_ultrasonic()
                if ultrasonic_data:
                    publish_data(ultrasonic_data, INFLUX_BUCKET_SENSOR, TOPICS["ultrasonic"])

            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Script interrupted. Shutting down.")
    finally:
        if dht_device:
            dht_device.exit()
        mqtt_client.loop_stop()
        influx_client.close()
        if GPIO:
            GPIO.cleanup()
        logger.info("Clients closed. Exiting.")
