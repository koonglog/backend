# KoongLog Sensor Data Exports

This directory contains exported sensor data for AI training.

- `all_sensor_readings.csv`: All rows from `raw_sensor_readings`
- `all_sensor_readings.json`: Pretty JSON version of all `raw_sensor_readings` rows
- `all_noise_events.csv`: All rows from `noise_events`
- `all_noise_events.json`: Pretty JSON version of all `noise_events` rows
- `export_summary.json`: Row counts and export file paths

`raw_sensor_readings` contains all received sensor values. `noise_events` contains only events that the AI service classified as meaningful.
