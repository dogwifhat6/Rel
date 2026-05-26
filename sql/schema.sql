-- PostgreSQL schema and sample rows for Voice-to-SQL demo
CREATE TABLE IF NOT EXISTS city_metrics (
    id          SERIAL PRIMARY KEY,
    city        TEXT    NOT NULL,
    temperature INTEGER NOT NULL,   -- Celsius, 0–50
    humidity    INTEGER NOT NULL,   -- percent, 0–100
    "range"     INTEGER NOT NULL    -- distance / score 0–1000 (quoted: range is reserved)
);

INSERT INTO city_metrics (city, temperature, humidity, "range") VALUES
    ('Mumbai', 32, 75, 400),
    ('Delhi', 38, 40, 600),
    ('Pune', 28, 88, 250),
    ('Chennai', 31, 80, 500),
    ('Kolkata', 29, 90, 350),
    ('Bengaluru', 24, 65, 200);
