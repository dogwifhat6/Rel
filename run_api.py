#!/usr/bin/env python3
"""Run the Voice-to-SQL REST API."""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port, reload=os.environ.get("API_RELOAD", "0") == "1")
