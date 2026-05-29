-- ============================================================
-- Voice-to-SQL  ·  Database Initialization Script
-- Runs automatically on first `docker-compose up`
-- ============================================================

-- ── Table 1: cities (master list with bounding boxes) ──────
CREATE TABLE IF NOT EXISTS cities (
    city_id           SERIAL PRIMARY KEY,
    city_name         VARCHAR(100) UNIQUE NOT NULL,
    state             VARCHAR(100) NOT NULL,
    boundary_lat_min  NUMERIC(10,6) NOT NULL,
    boundary_lat_max  NUMERIC(10,6) NOT NULL,
    boundary_lon_min  NUMERIC(10,6) NOT NULL,
    boundary_lon_max  NUMERIC(10,6) NOT NULL
);

-- ── Table 2: alerts (alert metadata) ───────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    alert_id     SERIAL PRIMARY KEY,
    alert_type   VARCHAR(50) NOT NULL
                     CHECK (alert_type IN (
                         'HIGH_TEMP','EXTREME_HEAT','HIGH_HUMIDITY',
                         'LOW_HUMIDITY','EXTREME_BANDWIDTH','GENERAL'
                     )),
    severity     VARCHAR(20) NOT NULL
                     CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    detected_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── Table 3: alert_readings (one per alert, location + sensor) ─
CREATE TABLE IF NOT EXISTS alert_readings (
    reading_id   SERIAL PRIMARY KEY,
    alert_id     INTEGER NOT NULL REFERENCES alerts(alert_id) ON DELETE CASCADE,
    latitude     NUMERIC(10,6) NOT NULL,
    longitude    NUMERIC(10,6) NOT NULL,
    temperature  NUMERIC(5,1),     -- 0–50 °C
    humidity     NUMERIC(5,1),     -- 0–100 %
    bandwidth    NUMERIC(6,1)      -- -100–100
);

-- ── Indexes ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_readings_alert ON alert_readings(alert_id);
CREATE INDEX IF NOT EXISTS idx_readings_geo   ON alert_readings(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_alerts_type    ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_sev     ON alerts(severity);


-- ============================================================
-- Seed Data  (only if the cities table is empty)
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cities LIMIT 1) THEN

        -- ── 15 Indian cities with bounding boxes ───────────
        INSERT INTO cities (city_name, state, boundary_lat_min, boundary_lat_max, boundary_lon_min, boundary_lon_max) VALUES
            ('Mumbai',      'Maharashtra',     18.8900, 19.2700, 72.7700, 72.9800),
            ('Delhi',       'Delhi',           28.4000, 28.8800, 76.8400, 77.3500),
            ('Bengaluru',   'Karnataka',       12.8300, 13.1400, 77.4600, 77.7800),
            ('Chennai',     'Tamil Nadu',      12.8300, 13.2300, 80.1600, 80.3300),
            ('Kolkata',     'West Bengal',     22.4500, 22.6300, 88.2900, 88.4400),
            ('Hyderabad',   'Telangana',       17.2900, 17.5400, 78.3500, 78.5800),
            ('Pune',        'Maharashtra',     18.4300, 18.6300, 73.7600, 73.9500),
            ('Ahmedabad',   'Gujarat',         22.9400, 23.1200, 72.5000, 72.6700),
            ('Jaipur',      'Rajasthan',       26.8000, 27.0000, 75.7000, 75.8900),
            ('Lucknow',     'Uttar Pradesh',   26.7800, 26.9200, 80.8800, 81.0200),
            ('Surat',       'Gujarat',         21.1300, 21.2500, 72.7700, 72.8800),
            ('Nagpur',      'Maharashtra',     21.0800, 21.1900, 79.0100, 79.1400),
            ('Indore',      'Madhya Pradesh',  22.6400, 22.7800, 75.8000, 75.9300),
            ('Bhopal',      'Madhya Pradesh',  23.1800, 23.3100, 77.3500, 77.4700),
            ('Visakhapatnam','Andhra Pradesh',  17.6800, 17.7800, 83.2200, 83.3500);

        -- ── 40 alerts with varied types / severities ───────
        INSERT INTO alerts (alert_type, severity, detected_at) VALUES
            ('HIGH_TEMP',          'HIGH',     '2025-05-01 08:30:00'),
            ('EXTREME_HEAT',       'CRITICAL', '2025-05-01 12:00:00'),
            ('HIGH_HUMIDITY',      'MEDIUM',   '2025-05-02 06:15:00'),
            ('LOW_HUMIDITY',       'LOW',      '2025-05-02 14:45:00'),
            ('EXTREME_BANDWIDTH',  'HIGH',     '2025-05-03 09:00:00'),
            ('GENERAL',            'LOW',      '2025-05-03 18:30:00'),
            ('HIGH_TEMP',          'MEDIUM',   '2025-05-04 07:00:00'),
            ('EXTREME_HEAT',       'CRITICAL', '2025-05-04 13:20:00'),
            ('HIGH_HUMIDITY',      'HIGH',     '2025-05-05 05:45:00'),
            ('LOW_HUMIDITY',       'MEDIUM',   '2025-05-05 16:10:00'),
            ('EXTREME_BANDWIDTH',  'CRITICAL', '2025-05-06 10:30:00'),
            ('GENERAL',            'LOW',      '2025-05-06 20:00:00'),
            ('HIGH_TEMP',          'HIGH',     '2025-05-07 08:15:00'),
            ('EXTREME_HEAT',       'HIGH',     '2025-05-07 14:00:00'),
            ('HIGH_HUMIDITY',      'MEDIUM',   '2025-05-08 04:30:00'),
            ('LOW_HUMIDITY',       'LOW',      '2025-05-08 15:00:00'),
            ('EXTREME_BANDWIDTH',  'MEDIUM',   '2025-05-09 11:00:00'),
            ('GENERAL',            'HIGH',     '2025-05-09 19:45:00'),
            ('HIGH_TEMP',          'CRITICAL', '2025-05-10 09:30:00'),
            ('EXTREME_HEAT',       'CRITICAL', '2025-05-10 13:45:00'),
            ('HIGH_HUMIDITY',      'HIGH',     '2025-05-11 06:00:00'),
            ('LOW_HUMIDITY',       'MEDIUM',   '2025-05-11 14:30:00'),
            ('EXTREME_BANDWIDTH',  'HIGH',     '2025-05-12 10:00:00'),
            ('GENERAL',            'LOW',      '2025-05-12 17:15:00'),
            ('HIGH_TEMP',          'MEDIUM',   '2025-05-13 07:45:00'),
            ('EXTREME_HEAT',       'HIGH',     '2025-05-13 12:30:00'),
            ('HIGH_HUMIDITY',      'CRITICAL', '2025-05-14 05:00:00'),
            ('LOW_HUMIDITY',       'LOW',      '2025-05-14 16:00:00'),
            ('EXTREME_BANDWIDTH',  'MEDIUM',   '2025-05-15 08:00:00'),
            ('GENERAL',            'MEDIUM',   '2025-05-15 21:00:00'),
            ('HIGH_TEMP',          'HIGH',     '2025-05-16 09:00:00'),
            ('EXTREME_HEAT',       'CRITICAL', '2025-05-16 14:15:00'),
            ('HIGH_HUMIDITY',      'MEDIUM',   '2025-05-17 06:30:00'),
            ('LOW_HUMIDITY',       'HIGH',     '2025-05-17 15:30:00'),
            ('EXTREME_BANDWIDTH',  'CRITICAL', '2025-05-18 11:30:00'),
            ('GENERAL',            'LOW',      '2025-05-18 18:00:00'),
            ('HIGH_TEMP',          'MEDIUM',   '2025-05-19 08:00:00'),
            ('EXTREME_HEAT',       'HIGH',     '2025-05-19 13:00:00'),
            ('HIGH_HUMIDITY',      'HIGH',     '2025-05-20 04:15:00'),
            ('GENERAL',            'CRITICAL', '2025-05-20 22:00:00');

        -- ── 40 alert_readings (one per alert, inside city bounding boxes) ──
        INSERT INTO alert_readings (alert_id, latitude, longitude, temperature, humidity, bandwidth) VALUES
            -- Mumbai readings
            ( 1, 19.0760, 72.8777, 42.5, 78.0,  15.0),
            ( 2, 19.0330, 72.8500, 48.0, 65.0,  -5.0),
            ( 3, 18.9500, 72.8300, 35.0, 95.0,  20.0),
            -- Delhi readings
            ( 4, 28.6139, 77.2090, 38.0, 18.0,  30.0),
            ( 5, 28.7041, 77.1025, 40.0, 25.0,  95.0),
            ( 6, 28.5355, 77.3910, 36.0, 42.0,  10.0),
            -- Bengaluru readings
            ( 7, 12.9716, 77.5946, 34.0, 55.0,  25.0),
            ( 8, 12.9352, 77.6245, 46.0, 40.0, -10.0),
            -- Chennai readings
            ( 9, 13.0827, 80.2707, 37.0, 92.0,  18.0),
            (10, 13.0500, 80.2500, 33.0, 38.0,  22.0),
            -- Kolkata readings
            (11, 22.5726, 88.3639, 35.0, 88.0,  98.0),
            (12, 22.5500, 88.3500, 31.0, 50.0,   5.0),
            -- Hyderabad readings
            (13, 17.3850, 78.4867, 41.0, 70.0,  12.0),
            (14, 17.4400, 78.3500, 44.0, 55.0,  -8.0),
            -- Pune readings
            (15, 18.5204, 73.8567, 30.0, 90.0,  28.0),
            (16, 18.5000, 73.8000, 29.0, 22.0,  35.0),
            -- Ahmedabad readings
            (17, 23.0225, 72.5714, 39.0, 30.0,  60.0),
            (18, 23.0500, 72.6000, 37.0, 72.0,  15.0),
            -- Jaipur readings
            (19, 26.9124, 75.7873, 47.0, 15.0,  40.0),
            (20, 26.8500, 75.8000, 49.0, 12.0, -20.0),
            -- Lucknow readings
            (21, 26.8467, 80.9462, 36.0, 85.0,  10.0),
            (22, 26.8800, 80.9500, 34.0, 45.0,  50.0),
            -- Surat readings
            (23, 21.1702, 72.8311, 38.0, 80.0,  75.0),
            (24, 21.2000, 72.8500, 32.0, 48.0,   8.0),
            -- Nagpur readings
            (25, 21.1458, 79.0882, 35.0, 60.0,  20.0),
            (26, 21.1200, 79.0500, 43.0, 50.0,  -3.0),
            -- Indore readings
            (27, 22.7196, 75.8577, 33.0, 98.0,  14.0),
            (28, 22.6800, 75.8200, 31.0, 20.0,  42.0),
            -- Bhopal readings
            (29, 23.2599, 77.4126, 36.0, 35.0,  55.0),
            (30, 23.2000, 77.4000, 34.0, 65.0,  18.0),
            -- Visakhapatnam readings
            (31, 17.6868, 83.2185, 40.0, 82.0,  22.0),
            (32, 17.7300, 83.3000, 45.0, 75.0, -15.0),
            -- Cross-city spread (alerts 33–40)
            (33, 19.1000, 72.9000, 38.0, 88.0,  30.0),   -- Mumbai
            (34, 28.6500, 77.2300, 42.0, 28.0,  65.0),   -- Delhi
            (35, 13.1000, 80.2800, 39.0, 90.0,  90.0),   -- Chennai
            (36, 22.4800, 88.3200, 30.0, 55.0,  12.0),   -- Kolkata
            (37, 18.5500, 73.8800, 33.0, 62.0,  25.0),   -- Pune
            (38, 17.4200, 78.5000, 44.0, 48.0, -12.0),   -- Hyderabad
            (39, 12.8800, 77.5000, 36.0, 85.0,  20.0),   -- Bengaluru
            (40, 26.9000, 75.7500, 48.0, 10.0,  35.0);   -- Jaipur

    END IF;
END $$;
