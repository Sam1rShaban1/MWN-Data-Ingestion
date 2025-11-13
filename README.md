# Project: Raspberry Pi Sensor & Metrics Monitoring

This project uses a Python script to collect sensor data (DHT11 Temperature/Humidity, HC-SR04 Ultrasonic Distance) and system metrics from a Raspberry Pi. The data is published to an EMQX Cloud MQTT Broker and simultaneously stored in an InfluxDB Cloud instance for long-term analysis and visualization.

### Monitored Data Points
*   **Sensors (from `sensor` bucket):**
    *   Temperature (`temperature`)
    *   Humidity (`humidity`)
    *   Distance (`distance_cm`)
*   **System Metrics (from `metrics` bucket):**
    *   CPU Usage (`cpu_percent`)
    *   RAM Usage (`ram_percent`)
    *   Disk Usage (`disk_percent`)
    *   Core Temperature (`pi_temp`)

### System Architecture
The data flows through the system as follows:

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
sudo apt-get install -y libgpiod3

# 2. Install required Python libraries
pip3 install psutil paho-mqtt influxdb-client-3 adafruit-circuitpython-dht --break-system-packages
```

### C. Configuration
The script requires credentials and connection details.

1.  **Place Certificate:** Copy the `server-ca.crt` file into the same directory as the Python script.
2.  **Set Environment Variables:** For security, it is best to set your credentials as environment variables.

    ```bash
    export INFLUXDB_TOKEN="your-influxdb-api-token"
    export MQTT_USER="your-mqtt-username"
    export MQTT_PASS="your-mqtt-password"
    ```
    You can add these lines to your `~/.bashrc` file to make them permanent.

### D. Running the Script
With the configuration in place, execute the script:
```bash
python3 pi_sensor_metrics.py
```

---

## 2. Connecting Grafana for Visualization

You can visualize data in Grafana in two ways: from InfluxDB for historical trends, and directly from EMQX for live, real-time views.

### Method 1: Visualizing Historical Data from InfluxDB (Recommended)

This method queries the data stored in your InfluxDB Cloud instance.

#### A. Add InfluxDB as a Data Source
1.  In Grafana, navigate to **Connections** -> **Data Sources**.
2.  Click **Add data source** and search for **InfluxDB**.
3.  Configure the settings:
    *   **Query Language:** `Flux`
    *   **URL:** `https://eu-central-1-1.aws.cloud2.influxdata.com` (use your region's URL).
    *   **Organization:** `Mobile and Wireless Networks`
    *   **Token:** Paste your InfluxDB API Token (the value from `INFLUXDB_TOKEN`).
4.  Click **Save & Test**. You should see a success message.

#### B. Create Dashboard Panels with Flux Queries

**Example Query 1: Temperature from a specific Pi**
```flux
from(bucket: "sensor")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "sensor")
  |> filter(fn: (r) => r.device == "pi15")  // Hardcoded device name
  |> filter(fn: (r) => r._field == "temperature")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean_temp")
```

**Example Query 2: Ultrasonic Distance (using a Grafana Variable)**
To make your dashboard dynamic, create a Grafana variable named `device`.
1.  Go to Dashboard Settings -> Variables -> New variable.
2.  Set **Type** to `Query`, select your InfluxDB source.
3.  Use this Flux query to populate the variable with device names:
    ```flux
    import "influxdata/influxdb/schema"
    schema.tagValues(bucket: "metrics", tag: "device")
    ```
4.  Now, use `$device` in your panel queries:
    ```flux
    from(bucket: "sensor")
      |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
      |> filter(fn: (r) => r._measurement == "sensor")
      |> filter(fn: (r) => r.device == "${device}") // Use the variable
      |> filter(fn: (r) => r._field == "distance_cm")
      |> yield(name: "distance")
    ```

### Method 2: Visualizing Live Data from EMQX (MQTT)

This method gives you a real-time view of the data as it's published.

#### A. Add MQTT as a Data Source
1.  In Grafana, go to **Connections** -> **Data Sources**.
2.  Search for and install the **Grafana MQTT data source** plugin if it's not already installed.
3.  Add it as a new data source and configure it:
    *   **URL:** `mqtts://t0761115.ala.eu-central-1.emqxsl.com` (note the `mqtts://` prefix).
    *   **Port:** `8883`
    *   **Authentication:** Enable **Basic Auth** and enter your MQTT Username and Password.
    *   **TLS/SSL:**
        *   Enable **TLS Client Auth**.
        *   Set **With CA Cert** to `true`.
        *   Paste the **entire content** of your `server-ca.crt` file into the "TLS CA Cert" text box.
4.  Click **Save & Test**.

#### B. Create a Live Dashboard Panel
1.  Create a new panel and select your MQTT data source.
2.  In the query editor, set the **Topic** to subscribe to, for example: `pi15/dht11`.
3.  The data will arrive as a JSON string. Use Grafana's **Transform** tab to parse it:
    *   Add a **Parse fields** transformation.
    *   **Source:** Select the field containing the MQTT message (usually `message`).
    *   **Format:** `JSON`
4.  This will extract the fields (`temperature`, `humidity`, etc.) which you can then use in your visualization. For a live graph, set the panel's refresh rate to a low value (e.g., 5s).
