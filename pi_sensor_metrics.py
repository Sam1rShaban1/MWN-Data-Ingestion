#!/usr/bin/env python3
import time
import json
import logging
import psutil
import os
import socket
import random
from datetime import datetime
import ssl
import paho.mqtt.client as mqtt
from influxdb_client_3 import InfluxDBClient3, Point


DEVICE_NAME = socket.gethostname()
DHT_PIN = 4
TRIG_PIN = 23
ECHO_PIN = 24


BROKER = "t0761115.ala.eu-central-1.emqxsl.com"  # check Deployment Overview
PORT = 8883  # TLS/SSL port from Deployment Overview
USERNAME = "your_emqx_username"
PASSWORD = "your_emqx_password"
CA_CERT = "./server-ca.crt"

TOPIC_METRICS = f"{DEVICE_NAME}/metrics"
TOPIC_DHT11 = f"{DEVICE_NAME}/dht11"
TOPIC_ULTRASONIC = f"{DEVICE_NAME}/ultrasonic"

CLIENT_ID = f"python-mqtt-{random.randint(0,1000)}"


INFLUX_HOST = "https://eu-central-1-1.aws.cloud2.influxdata.com"
INFLUX_ORG = "Mobile and Wireless Networks"
INFLUX_BUCKET_SENSOR = "sensor"
INFLUX_BUCKET_METRICS = "metrics"
INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN")
influx_client = InfluxDBClient3(host=INFLUX_HOST, token=INFLUX_TOKEN, org=INFLUX_ORG)


SENSOR_INTERVAL = 10
METRICS_INTERVAL = 60


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


try:
    import Adafruit_DHT
    DHT_AVAILABLE = True
except ImportError:
    DHT_AVAILABLE = False

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

if GPIO_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to EMQX Serverless broker!")
    else:
        logger.error(f"Failed to connect, return code {rc}")

def connect_mqtt():
    client = mqtt.Client(CLIENT_ID)
    client.username_pw_set(USERNAME, PASSWORD)
    client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_connect = on_connect
    client.connect(BROKER, PORT)
    return client

mqtt_client = connect_mqtt()
mqtt_client.loop_start()


def read_dht11():
    if not DHT_AVAILABLE:
        return None
    h, t = Adafruit_DHT.read_retry(Adafruit_DHT.DHT11, DHT_PIN)
    if h is not None and t is not None:
        return {"temperature": round(t,1), "humidity": round(h,1), "timestamp": datetime.utcnow().isoformat()}
    return None

def read_ultrasonic():
    if not GPIO_AVAILABLE:
        return None
    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, False)
    start, end = 0, 0
    while GPIO.input(ECHO_PIN) == 0:
        start = time.time()
    while GPIO.input(ECHO_PIN) == 1:
        end = time.time()
    distance_cm = round(((end - start) * 34300) / 2, 2)
    return {"distance_cm": distance_cm, "timestamp": datetime.utcnow().isoformat()}

def read_pi_metrics():
    metrics = {}
    metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
    metrics["per_core"] = psutil.cpu_percent(interval=None, percpu=True)
    metrics["ram_percent"] = psutil.virtual_memory().percent
    metrics["disk_percent"] = psutil.disk_usage('/').percent
    metrics["load_avg"] = os.getloadavg()
    metrics["net_io"] = psutil.net_io_counters()._asdict()
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            metrics["pi_temp"] = float(f.read().strip()) / 1000
    except FileNotFoundError:
        metrics["pi_temp"] = None
    metrics["uptime_sec"] = time.time() - psutil.boot_time()
    metrics["timestamp"] = datetime.utcnow().isoformat()
    return metrics

def publish_mqtt(topic, payload):
    mqtt_client.publish(topic, json.dumps(payload))
    logger.info(f"MQTT Published → {topic}: {payload}")

def publish_influx(payload, bucket):
    point = Point.from_dict(payload)
    try:
        influx_client.write(bucket=bucket, record=point)
    except Exception as e:
        logger.error(f"Influx write error: {e}")


next_metrics_time = time.time()
while True:
    # Pi metrics
    metrics_data = read_pi_metrics()
    publish_mqtt(TOPIC_METRICS, metrics_data)
    publish_influx(metrics_data, INFLUX_BUCKET_METRICS)
    
    # Sensor data
    if DHT_AVAILABLE:
        sensor_data = read_dht11()
        if sensor_data:
            publish_mqtt(TOPIC_DHT11, sensor_data)
            publish_influx(sensor_data, INFLUX_BUCKET_SENSOR)
    elif GPIO_AVAILABLE:
        sensor_data = read_ultrasonic()
        if sensor_data:
            publish_mqtt(TOPIC_ULTRASONIC, sensor_data)
            publish_influx(sensor_data, INFLUX_BUCKET_SENSOR)
    
    time.sleep(SENSOR_INTERVAL)
