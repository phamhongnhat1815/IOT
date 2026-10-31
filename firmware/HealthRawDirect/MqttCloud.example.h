#pragma once
// configure_mqtt_cloud.py generates MqttCloud.h with the broker's CA and credentials.
constexpr char CLOUD_HOST[] = "YOUR_MQTT_HOST";
constexpr unsigned short CLOUD_PORT = 8883;
constexpr char CLOUD_USER[] = "YOUR_MQTT_USERNAME";
constexpr char CLOUD_PASSWORD[] = "YOUR_MQTT_PASSWORD";
constexpr char CLOUD_CA[] = "PASTE_CA_PEM_HERE";
