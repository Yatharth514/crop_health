
#include <Arduino.h>
#include <DHTesp.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <time.h>

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef SENSOR_API_URL
#define SENSOR_API_URL "http://host.wokwi.internal:8000/api/sensors/readings"
#endif

#ifndef SENSOR_DEVICE_ID
#define SENSOR_DEVICE_ID "wokwi-esp32-01"
#endif

#ifndef SENSOR_DEVICE_TOKEN
#define SENSOR_DEVICE_TOKEN ""
#endif

// ---------------- PIN CONFIGURATION ----------------

#define DHT_PIN 16
#define POT_PIN 34
#define LED_PIN 2

// ---------------- SENSOR CONFIGURATION ----------------

DHTesp dht;
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ---------------- FUNCTION PROTOTYPES ----------------

void readSensors();
void updateLCD();
void printSerialData();
void updateMovingAverage(float newTemperature, float newHumidity);
void evaluateRisk();
void updateLED();
void networkTask(void *parameter);
void queueSensorReading();

// ---------------- NETWORK CONFIGURATION ----------------

const unsigned long UPLOAD_INTERVAL_MS = 10000;
const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 2500;
const int NETWORK_QUEUE_LENGTH = 1;

struct SensorSnapshot {
    float temperature;
    float humidity;
    int gasReading;
    uint32_t sequence;
    time_t measuredAtEpoch;
};

QueueHandle_t sensorQueue = nullptr;
bool latestReadingValid = false;
uint32_t bootId = 0;
uint32_t readingSequence = 0;

// ---------------- ALERT THRESHOLDS ----------------

const float TEMP_THRESHOLD = 35.0;
const float HUMIDITY_THRESHOLD = 80.0;
const int GAS_THRESHOLD = 3000;

// ---------------- MOVING AVERAGE CONFIGURATION ----------------

#define WINDOW_SIZE 5

float temperatureReadings[WINDOW_SIZE] = {0};
float humidityReadings[WINDOW_SIZE] = {0};

int readingIndex = 0;
int validReadings = 0;

// ---------------- SENSOR VARIABLES ----------------

float temperature = 0.0;
float humidity = 0.0;

int rawGasValue = 0;
int gasValue = 0;

int riskCount = 0;

String riskLevel = "NORMAL";

// ---------------- TIMING CONFIGURATION ----------------

unsigned long previousMillis = 0;
const unsigned long SENSOR_INTERVAL = 2000;
unsigned long previousUploadMillis = 0;

unsigned long previousLedMillis = 0;
const unsigned long LED_BLINK_INTERVAL = 500;

bool ledState = false;

// ---------------- SETUP ----------------

void setup() {

    Serial.begin(115200);

    // Initialize DHT22
    dht.setup(DHT_PIN, DHTesp::DHT22);

    // Initialize I2C
    Wire.begin(21, 22);

    // Initialize LCD
    lcd.init();
    lcd.backlight();

    // Initialize LED
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    // Startup message
    lcd.setCursor(0, 0);
    lcd.print("SMART CROP NODE");

    lcd.setCursor(0, 1);
    lcd.print("Initializing...");

    Serial.println("================================");
    Serial.println(" SMART CROP MONITORING NODE");
    Serial.println("================================");

    Serial.print("Sensor API: ");
    Serial.println(SENSOR_API_URL);
    Serial.print("Device ID: ");
    Serial.println(SENSOR_DEVICE_ID);
    Serial.println(SENSOR_DEVICE_TOKEN[0] == '\0'
        ? "Device token is not configured; authenticated uploads will be skipped."
        : "Device token configured (value hidden).");

    sensorQueue = xQueueCreate(NETWORK_QUEUE_LENGTH, sizeof(SensorSnapshot));
    if (sensorQueue == nullptr) {
        Serial.println("ERROR: Could not create sensor upload queue.");
    } else {
        bootId = esp_random();
        BaseType_t taskCreated = xTaskCreatePinnedToCore(
            networkTask,
            "sensor-network",
            8192,
            nullptr,
            1,
            nullptr,
            0
        );
        if (taskCreated != pdPASS) {
            Serial.println("ERROR: Could not start network task; monitoring remains active.");
        }
    }

    delay(2000);

    lcd.clear();
}

// ---------------- MOVING AVERAGE ----------------

void updateMovingAverage(float newTemperature, float newHumidity) {

    temperatureReadings[readingIndex] = newTemperature;
    humidityReadings[readingIndex] = newHumidity;

    readingIndex = (readingIndex + 1) % WINDOW_SIZE;

    if (validReadings < WINDOW_SIZE) {
        validReadings++;
    }

    float temperatureSum = 0.0;
    float humiditySum = 0.0;

    for (int i = 0; i < validReadings; i++) {

        temperatureSum += temperatureReadings[i];
        humiditySum += humidityReadings[i];
    }

    temperature = temperatureSum / validReadings;
    humidity = humiditySum / validReadings;
}

// ---------------- RISK CLASSIFICATION ----------------

void evaluateRisk() {

    riskCount = 0;

    if (temperature > TEMP_THRESHOLD) {
        riskCount++;
    }

    if (humidity > HUMIDITY_THRESHOLD) {
        riskCount++;
    }

    if (gasValue > GAS_THRESHOLD) {
        riskCount++;
    }

    if (riskCount == 0) {
        riskLevel = "NORMAL";
    }
    else if (riskCount == 1) {
        riskLevel = "WARNING";
    }
    else {
        riskLevel = "CRITICAL";
    }
}

// ---------------- LED CONTROL ----------------

void updateLED() {

    unsigned long currentMillis = millis();

    if (riskLevel == "NORMAL") {

        ledState = false;
        digitalWrite(LED_PIN, LOW);
    }

    else if (riskLevel == "WARNING") {

        ledState = true;
        digitalWrite(LED_PIN, HIGH);
    }

    else if (riskLevel == "CRITICAL") {

        if (currentMillis - previousLedMillis >= LED_BLINK_INTERVAL) {

            previousLedMillis = currentMillis;

            ledState = !ledState;

            digitalWrite(LED_PIN, ledState ? HIGH : LOW);
        }
    }
}

// ---------------- SENSOR READING ----------------

void readSensors() {

    // Read DHT22
    TempAndHumidity data = dht.getTempAndHumidity();

    Serial.print("DHT22 Status: ");
    Serial.println(dht.getStatusString());

    // Validate readings
    if (isnan(data.temperature) || isnan(data.humidity)) {

        latestReadingValid = false;

        Serial.println("ERROR: DHT22 reading failed!");

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("DHT22 ERROR");

        lcd.setCursor(0, 1);
        lcd.print("Check sensor");

        riskLevel = "CRITICAL";
        updateLED();

        return;
    }

    // Update moving average
    updateMovingAverage(data.temperature, data.humidity);

    // Read potentiometer
    rawGasValue = analogRead(POT_PIN);

    // Convert ADC reading (0-4095) to simulated gas value (0-5000)
    gasValue = map(rawGasValue, 0, 4095, 0, 4095);

    // Evaluate environmental risk
    evaluateRisk();

    // Update LED
    updateLED();

    // Update LCD
    updateLCD();

    // Print sensor data
    printSerialData();

    latestReadingValid = true;
}

// ---------------- SENSOR UPLOAD QUEUE ----------------

void queueSensorReading() {
    if (sensorQueue == nullptr || !latestReadingValid) {
        return;
    }

    SensorSnapshot snapshot = {
        temperature,
        humidity,
        gasValue,
        ++readingSequence,
        time(nullptr)
    };

    // Keep the newest sample while networking is unavailable instead of
    // allowing a backlog to interfere with real-time sensor monitoring.
    if (xQueueOverwrite(sensorQueue, &snapshot) == pdPASS) {
        Serial.print("Queued sensor reading ");
        Serial.println(snapshot.sequence);
    }
}

// ---------------- ASYNC NETWORK / HTTP WORKER ----------------

void networkTask(void *parameter) {
    (void)parameter;
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin("Wokwi-GUEST", "", 6);
    Serial.println("Connecting to Wokwi-GUEST (channel 6)...");

    SensorSnapshot pendingSnapshot;
    bool hasPendingSnapshot = false;
    unsigned long lastWiFiAttempt = millis();
    unsigned long nextHttpAttempt = 0;
    bool ntpConfigured = false;

    for (;;) {
        if (!hasPendingSnapshot && sensorQueue != nullptr) {
            hasPendingSnapshot = xQueueReceive(
                sensorQueue,
                &pendingSnapshot,
                pdMS_TO_TICKS(250)
            ) == pdPASS;
        }

        if (WiFi.status() != WL_CONNECTED) {
            if (millis() - lastWiFiAttempt >= WIFI_RETRY_INTERVAL_MS) {
                lastWiFiAttempt = millis();
                Serial.println("Wi-Fi disconnected; retrying Wokwi-GUEST.");
                WiFi.disconnect();
                WiFi.begin("Wokwi-GUEST", "", 6);
            }
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        if (!ntpConfigured) {
            configTime(0, 0, "pool.ntp.org", "time.nist.gov");
            ntpConfigured = true;
            Serial.print("Wi-Fi connected. IP: ");
            Serial.println(WiFi.localIP());
        }

        if (SENSOR_DEVICE_TOKEN[0] == '\0') {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        if (!hasPendingSnapshot || millis() < nextHttpAttempt) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        char readingId[40];
        snprintf(
            readingId,
            sizeof(readingId),
            "%08lx:%lu",
            static_cast<unsigned long>(bootId),
            static_cast<unsigned long>(pendingSnapshot.sequence)
        );

        char measuredAt[32] = "";
        if (pendingSnapshot.measuredAtEpoch >= 1700000000) {
            struct tm utcTime;
            gmtime_r(&pendingSnapshot.measuredAtEpoch, &utcTime);
            strftime(measuredAt, sizeof(measuredAt), "%Y-%m-%dT%H:%M:%SZ", &utcTime);
        }

        char payload[256];
        int payloadLength;
        if (measuredAt[0] != '\0') {
            payloadLength = snprintf(
                payload,
                sizeof(payload),
                "{\"device_id\":\"%s\",\"reading_id\":\"%s\",\"temperature\":%.2f,\"humidity\":%.2f,\"gas_reading\":%d,\"measured_at\":\"%s\"}",
                SENSOR_DEVICE_ID,
                readingId,
                pendingSnapshot.temperature,
                pendingSnapshot.humidity,
                pendingSnapshot.gasReading,
                measuredAt
            );
        } else {
            payloadLength = snprintf(
                payload,
                sizeof(payload),
                "{\"device_id\":\"%s\",\"reading_id\":\"%s\",\"temperature\":%.2f,\"humidity\":%.2f,\"gas_reading\":%d}",
                SENSOR_DEVICE_ID,
                readingId,
                pendingSnapshot.temperature,
                pendingSnapshot.humidity,
                pendingSnapshot.gasReading
            );
        }

        if (payloadLength <= 0 || payloadLength >= sizeof(payload)) {
            Serial.println("ERROR: Could not format sensor JSON; dropping sample.");
            hasPendingSnapshot = false;
            continue;
        }

        WiFiClient client;
        HTTPClient http;
        http.setTimeout(HTTP_TIMEOUT_MS);
        http.setConnectTimeout(HTTP_TIMEOUT_MS);

        Serial.print("POST ");
        Serial.print(SENSOR_API_URL);
        Serial.print(" reading_id=");
        Serial.println(readingId);

        if (!http.begin(client, SENSOR_API_URL)) {
            Serial.println("HTTP setup failed; sample will be retried.");
            nextHttpAttempt = millis() + HTTP_RETRY_INTERVAL_MS;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        http.addHeader("Content-Type", "application/json");
        http.addHeader("X-Device-Token", SENSOR_DEVICE_TOKEN);
        int statusCode = http.POST(reinterpret_cast<uint8_t *>(payload), payloadLength);

        Serial.print("Sensor API HTTP status: ");
        Serial.println(statusCode);
        if (statusCode > 0) {
            String responseBody = http.getString();
            Serial.print("Sensor API response: ");
            Serial.println(responseBody);
        } else {
            Serial.print("HTTP transport error: ");
            Serial.println(http.errorToString(statusCode));
        }
        http.end();

        if (statusCode == HTTP_CODE_CREATED || statusCode == HTTP_CODE_OK) {
            hasPendingSnapshot = false;
            nextHttpAttempt = 0;
        } else {
            // Retry the same reading_id: server-side idempotency prevents a
            // duplicate if the server stored it but its response was lost.
            nextHttpAttempt = millis() + HTTP_RETRY_INTERVAL_MS;
        }
    }
}

// ---------------- LCD DISPLAY ----------------

void updateLCD() {

    lcd.clear();

    lcd.setCursor(0, 0);

    lcd.print("T:");
    lcd.print(temperature, 1);
    lcd.print("C H:");
    lcd.print(humidity, 0);
    lcd.print("%");

    lcd.setCursor(0, 1);

    lcd.print("G:");
    lcd.print(gasValue);
    lcd.print(" ");
    lcd.print(riskLevel);
}

// ---------------- SERIAL MONITOR ----------------

void printSerialData() {

    Serial.println("\n--------- SENSOR DATA ---------");

    Serial.print("Average Temperature: ");
    Serial.print(temperature);
    Serial.println(" C");

    Serial.print("Average Humidity: ");
    Serial.print(humidity);
    Serial.println(" %");

    Serial.print("Valid Readings: ");
    Serial.println(validReadings);

    Serial.print("Raw ADC Value: ");
    Serial.println(rawGasValue);

    Serial.print("Simulated Gas Value: ");
    Serial.println(gasValue);

    Serial.print("Exceeded Thresholds: ");
    Serial.println(riskCount);

    Serial.print("Environmental Risk: ");
    Serial.println(riskLevel);

    Serial.println("-------------------------------");
}

// ---------------- MAIN LOOP ----------------

void loop() {

    unsigned long currentMillis = millis();

    // Periodic sensor reading
    if (currentMillis - previousMillis >= SENSOR_INTERVAL) {

        previousMillis = currentMillis;

        readSensors();
    }

    if (currentMillis - previousUploadMillis >= UPLOAD_INTERVAL_MS) {
        previousUploadMillis = currentMillis;
        queueSensorReading();
    }

    // Continuously update LED blinking
    updateLED();
}

