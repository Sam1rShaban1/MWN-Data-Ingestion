# Raspberry Pi Sensor & Metrics Monitoring

This project uses a Python script to collect a comprehensive set of sensor data (DHT11, HC-SR04) and detailed system metrics from a Raspberry Pi. The data is published to an EMQX Cloud MQTT Broker and simultaneously stored in an InfluxDB Cloud instance for long-term analysis and visualization.

### Monitored Data Points

The script collects a rich set of metrics, which are stored in InfluxDB under two main measurements: `sensor` and `metrics`.

*   **Sensor Data (`sensor` measurement):**
    *   Temperature & Humidity (`temperature`, `humidity`) from the DHT11.
    *   Distance (`distance_cm`) from the HC-SR04 ultrasonic sensor.
*   **Detailed System Metrics (`metrics` measurement):**
    *   **CPU:** Overall Usage (`cpu_percent`), Per-Core Usage (`cpu_core_0_percent`, etc.), Core Frequency (`cpu_freq_mhz`), and Load Average (`load_avg_1m`, `5m`, `15m`).
    *   **Memory:** Total/Used RAM & Swap in MB, and usage percentages.
    *   **Disk:** Total/Used Disk space in GB, and usage percentage for the root partition.
    *   **Network:** Bytes/packets sent & received, errors, and dropped packets.
    *   **System:** Core Temperature (`pi_temp_c`), uptime, and total running processes.

### System Architecture

```
                  ┌──────────────────┐      ┌────────────────────┐
Raspberry Pi ───► │ EMQX Cloud (MQTT)├─────►│ Grafana (Live Data)│
(Python Script)   └──────────────────┘      └────────────────────┘
       │
       │              ┌────────────────┐      ┌───────────────────────┐
       └─────────────►│ InfluxDB Cloud ├─────►│ Grafana (Historical)  │
                      └────────────────┘      └───────────────────────┘
```

---

## 1. Setup & Installation on Raspberry Pi

### A. Hardware Requirements
*   Raspberry Pi (running Raspberry Pi OS, Bookworm recommended).
*   **DHT11 Sensor:** Data pin connected to **BCM Pin 4**.
*   **HC-SR04 Ultrasonic Sensor:** `TRIG` pin to **BCM Pin 23**, `ECHO` pin to **BCM Pin 24**.

### B. Software Dependencies
Run these commands in your Raspberry Pi terminal:
```bash
# 1. Update system and install utilities
sudo apt-get update
sudo apt-get install -y mosquitto-clients libgpiod3

# 2. Install required Python libraries
pip3 install psutil paho-mqtt influxdb-client-3 adafruit-circuitpython-dht --break-system-packages
```

### C. Configuration
1.  **Place Certificate:** Copy the `server-ca.crt` file into the same directory as the Python script.
2.  **Set Environment Variables:** For security, set your credentials as environment variables.
    ```bash
    export INFLUXDB_TOKEN="your-influxdb-api-token"
    export MQTT_USER="your-mqtt-username"
    export MQTT_PASS="your-mqtt-password"
    ```
    (Add these to `~/.bashrc` to make them permanent).

### D. Running the Script
Execute the script from the project directory:
```bash
python3 pi_sensor_metrics.py
```

---

## 2. Verifying Data Flow via MQTT

To confirm data is being sent over MQTT, you can use `mosquitto_sub` in a separate terminal.

**To subscribe to all topics from a specific Pi (e.g., `pi15`):**
```bash
mosquitto_sub \
  -h "t0761115.ala.eu-central-1.emqxsl.com" \
  -p 8883 \
  -u "your_user" \
  -P "your_pass" \
  --cafile "./server-ca.crt" \
  -t "pi15/#" \
  -v
```

**Example: Subscribing specifically to the DHT11 sensor data from `pi15`:**
```bash
mosquitto_sub \
  -h "t07611115.ala.eu-central-1.emqxsl.com" \
  -p 8883 \
  -u "samir" \
  -P "admin" \
  --cafile "./server-ca.crt" \
  -t "pi15/dht11" \
  -v
```

---

## 3. Connecting Grafana for Visualization

### A. Add InfluxDB as a Data Source (For Historical Data)
1.  In Grafana, go to **Connections** -> **Data Sources** and add a new **InfluxDB** source.
2.  Configure using the **Flux** query language:
    *   **Query Language** `SQL`
    *   **URL:** `https://eu-central-1-1.aws.cloud2.influxdata.com`
    *   **Database** `metrics` or `sensor`
    *   **Organization:** `Mobile and Wireless Networks`
    *   **Token:** ``` WCuamFMLkZLMO01_CZcIzTwbmwIi2g9cJPOtlnAFVM09QVCQ-O9elX7v2_lFuyl7DXNlrZ56X0teBOdAGaf-Og==```.
4.  Click **Save & Test**.

### B. Create Dashboard Panels with Updated Flux Queries

With the new detailed metrics, you can create more advanced visualizations.

**Example Query 1: Per-Core CPU Usage**
This query uses a regular expression to graph the usage of all CPU cores on a single panel.
```flux
SELECT
  "cpu_core_0_percent",
  "cpu_core_1_percent",
  "cpu_core_2_percent",
  "cpu_core_3_percent",
  "time"
FROM
  "metrics"
WHERE
  "time" >= $__timeFrom
  AND "time" <= $__timeTo
  AND "device" = 'pi4'
```

**Example Query 2: Network Traffic (Bytes Sent/Received)**
This query visualizes both incoming and outgoing network traffic.
```flux
SELECT
  "net_bytes_recv",
  "net_bytes_sent",
  "time"
FROM
  "metrics"
WHERE
  "time" >= $__timeFrom
  AND "time" <= $__timeTo
  AND "device" = 'pi4'
```

### C. Add MQTT as a Data Source (For Live Data)
1.  Install the **Grafana MQTT data source** plugin if needed.
2.  Add it as a new data source:
    *   **URL:** `mqtts://t0761115.ala.eu-central-1.emqxsl.com`
    *   **Port:** `8883`
    *   **Authentication:** Enable **Basic Auth** and enter your MQTT credentials.
    *   **TLS/SSL:** Enable **TLS Client Auth**, set **With CA Cert** to `true`, and paste the contents of `server-ca.crt` into the "TLS CA Cert" box.
3.  **Save & Test**. In a panel, subscribe to a topic (e.g., `pi4/metrics`) and use Grafana's **Transform** tab to parse the incoming JSON.
