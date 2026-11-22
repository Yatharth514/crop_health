
#include <DHTesp.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- PIN CONFIGURATION ----------------

#define DHT_PIN 15
#define POT_PIN 34
#define LED_PIN 2

// ---------------- SENSOR CONFIGURATION ----------------

DHTesp dht;

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ---------------- ALERT THRESHOLDS ----------------

const float TEMP_THRESHOLD = 35.0;
const float HUMIDITY_THRESHOLD = 80.0;
const int GAS_THRESHOLD = 3000;

// ---------------- VARIABLES ----------------

float temperature = 0.0;
float humidity = 0.0;

int rawGasValue = 0;
int gasValue = 0;

bool alertStatus = false;

unsigned long previousMillis = 0;

const unsigned long SENSOR_INTERVAL = 2000;

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

    delay(2000);

    lcd.clear();
}

// ---------------- SENSOR READING ----------------

void readSensors() {

    // Read DHT22
    TempAndHumidity data = dht.getTempAndHumidity();

    temperature = data.temperature;
    humidity = data.humidity;

    // Read potentiometer
    rawGasValue = analogRead(POT_PIN);

    // Convert ADC reading (0-4095)
    // into a simulated gas value (0-5000)
    gasValue = map(rawGasValue, 0, 4095, 0, 5000);

    // Validate DHT22 readings
    if (isnan(temperature) || isnan(humidity)) {

        Serial.println("ERROR: DHT22 reading failed!");

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("DHT22 ERROR");

        lcd.setCursor(0, 1);
        lcd.print("Check sensor");

        digitalWrite(LED_PIN, HIGH);

        return;
    }

    // Evaluate environmental conditions
    alertStatus =
        (temperature > TEMP_THRESHOLD) ||
        (humidity > HUMIDITY_THRESHOLD) ||
        (gasValue > GAS_THRESHOLD);

    // Control LED
    digitalWrite(LED_PIN, alertStatus ? HIGH : LOW);

    // Display readings
    updateLCD();

    // Print readings
    printSerialData();
}

// ---------------- LCD DISPLAY ----------------

void updateLCD() {

    lcd.clear();

    // First row: Temperature and humidity
    lcd.setCursor(0, 0);

    lcd.print("T:");
    lcd.print(temperature, 1);
    lcd.print("C H:");
    lcd.print(humidity, 0);
    lcd.print("%");

    // Second row: Gas value and status
    lcd.setCursor(0, 1);

    lcd.print("G:");
    lcd.print(gasValue);

    if (alertStatus) {
        lcd.print(" ALERT");
    }
    else {
        lcd.print(" NORMAL");
    }
}

// ---------------- SERIAL MONITOR ----------------

void printSerialData() {

    Serial.println("\n--------- SENSOR DATA ---------");

    Serial.print("Temperature: ");
    Serial.print(temperature);
    Serial.println(" C");

    Serial.print("Humidity: ");
    Serial.print(humidity);
    Serial.println(" %");

    Serial.print("Raw ADC Value: ");
    Serial.println(rawGasValue);

    Serial.print("Simulated Gas Value: ");
    Serial.println(gasValue);

    Serial.print("Environmental Status: ");

    if (alertStatus) {
        Serial.println("WARNING");
    }
    else {
        Serial.println("NORMAL");
    }

    Serial.println("-------------------------------");
}

// ---------------- MAIN LOOP ----------------

void loop() {

    unsigned long currentMillis = millis();

    if (currentMillis - previousMillis >= SENSOR_INTERVAL) {

        previousMillis = currentMillis;

        readSensors();
    }
}
