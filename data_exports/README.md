# KoongLog Sensor Data Exports

This directory contains exported monitoring data from the local backend API.

- `sensor_readings_recent.json`: Recent rows from `GET /api/v1/sensor-readings/recent?limit=100`
- `noise_events_recent.json`: Recent rows from `GET /api/v1/noise-events/recent?limit=100`

`sensor_readings_recent.json` contains raw sensor readings. `noise_events_recent.json` contains events that the AI service classified as meaningful and that were stored in `noise_events`.
