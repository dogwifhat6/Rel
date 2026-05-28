# Use a lightweight official Python runtime as a parent image
FROM python:3.10-slim

# Install system dependencies required for sounddevice (PortAudio) and psycopg2 (postgres client compilation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libportaudio2 \
    portaudio19-dev \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy requirement files and project files
COPY requirements.txt .
COPY pyproject.toml .
COPY README.md .
COPY vtsql/ vtsql/
COPY voicetosqldatabase/ voicetosqldatabase/
COPY api/ api/
COPY app.py .
COPY run_api.py .

# Install dependencies and the package
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .

# Expose ports for both the FastAPI server (8000) and the Streamlit dashboard (8502)
EXPOSE 8000
EXPOSE 8502

# Environment variables to run Streamlit/API cleanly
ENV PYTHONUNBUFFERED=1

# Default command can be overridden to run the API or Streamlit dashboard
CMD ["streamlit", "run", "app.py", "--server.port=8502", "--server.address=0.0.0.0"]
