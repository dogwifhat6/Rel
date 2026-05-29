# Voice-to-SQL Database Query Dashboard & REST API (Prototype 2)

A fully-local, modular, and containerized Python application that translates natural-language questions (spoken or typed) into secure PostgreSQL queries. It executes them against a multi-table database and visualizes coordinate points dynamically using interactive geospatial maps.

---

## 🚀 Key Features

*   **Multi-AI Agentic Query Builder**:
    *   **Agent 1 (SQL Generator)**: Generates safe SQL statements using the local `llama3.2:3b` model.
    *   **Agent 2 (SQL Critic/Validator)**: Evaluates generated SQL against database schema constraints, case-sensitivity rules, and security policies.
    *   **Database Self-Healing**: Automatically feeds database driver errors back to the Generator agent for correction, looping up to 3 times before execution.
*   **High-Performance Semantic Caching**:
    *   Saves queries in a local SQLite vector database using Ollama embeddings.
    *   Matches semantically similar questions using cosine similarity, returning cached queries in **under 50ms** without invoking LLM models.
*   **Interactive Geospatial Maps (PyDeck)**:
    *   Plots coordinates dynamically onto a map, color-coded by alert severity (Red for `CRITICAL`, Orange for `HIGH`, etc.).
    *   Renders semi-transparent bounding box boundary polygons for cities to visually demonstrate spatial intersections.
*   **Premium Dark UI Styling**:
    *   Outfitted with a native space-navy dark theme ([.streamlit/config.toml](.streamlit/config.toml)), Google Font typography (*Outfit*), glassmorphic card widgets, smooth hover micro-animations, and an active red pulsing microphone badge.
*   **REST API Integration & Standalone Python Library**:
    *   Exposes endpoints via FastAPI (such as `/v1/nl-query`, `/v1/transcribe`, and `/v1/voice-query`).
    *   Exposes in-process logic so you can run `import voicetosqldatabase` in other scripts.

---

## 🛠️ Database Schema

The system joins three tables inside PostgreSQL dynamically using a spatial join on coordinates:

1.  **cities**: Contains cities, states, and coordinates bounding boxes (`boundary_lat_min`, `boundary_lat_max`, etc.).
2.  **alerts**: Contains alert metadata (`alert_type`, `severity`, and `detected_at`).
3.  **alert_readings**: Contains alert details, including temperature, humidity, bandwidth, and spatial coordinates (`latitude`, `longitude`).

---

## ⚙️ Prerequisites

Ensure you have the following services installed and running locally:

*   **Python**: Version `3.9` or higher.
*   **Ollama**: Install from [ollama.com](https://ollama.com) and pull the model:
    ```bash
    ollama pull llama3.2:3b
    ```
*   **PostgreSQL**: Configured with database `city_alerte` running on default port `5432`.
*   **PortAudio**: System library required for local microphone recording:
    *   **macOS**: `brew install portaudio`
    *   **Ubuntu/Debian**: `sudo apt-get install portaudio19-dev libportaudio2`

---

## 📦 Local Setup & Execution

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
By default, the database attempts connection on `localhost:5432` with username `postgres` and database name `city_alerte`. Define these environment variables if your local configuration differs:
```bash
export DB_HOST="your-db-host"
export DB_PORT="your-db-port"
export DB_NAME="city_alerte"
export DB_USER="your-db-user"
export DB_PASSWORD="your-db-password"
```

### 3. Launch Services
```bash
# Start the Streamlit UI Dashboard (Access at http://localhost:8502)
npm run dev

# Start the FastAPI REST API Server (Access at http://localhost:8000)
npm run api
```

---

## 🐳 Containerized Execution (Docker Compose)

The application is fully container-ready. You can build and spin up the PostgreSQL database container, the API server container, and the Streamlit dashboard container in one command:

```bash
docker-compose up --build
```
*   **Streamlit UI**: `http://localhost:8502`
*   **FastAPI API**: `http://localhost:8000`
*   *Note: Containers bridge dynamically to your host machine's Ollama instance over the network gateway (`host.docker.internal`).*

---

## 🐍 Programmatic Python Library Usage

You can install this repository as an editable python package to import Voice-to-SQL logic directly inside your other python applications:

```bash
# Install the package globally in your environment
pip install -e .
```

Then write scripts utilizing direct in-process pipelines:
```python
import voicetosqldatabase as vts

# 1. Run local in-process queries (no server needed)
result = vts.run_nl_query("Which city did the most recent critical alert come from?")
print(f"PostgreSQL SQL: {result['sql']}")
print(f"Results: {result['rows']}")

# 2. Or query programmatically via REST client (if api service is running)
client = vts.VoiceToSQLClient(base_url="http://localhost:8000")
data = client.nl_query("Show me all alerts in Mumbai")
```
*Note: An automated system precheck diagnostics module runs lazily during initial in-process executions to verify that Postgres, sounddevice, and Ollama are configured and healthy.*

---

## 🧪 Unit Testing

Run the local test suites to verify syntax compliance and mock agent correction loops:

```bash
.venv/bin/python -m unittest discover -s . -p "*test_logic.py"
```
