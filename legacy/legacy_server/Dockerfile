# Use Python 3.9 slim image for compatibility
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY legacy/legacy_server/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project structure (needed for imports from ingester and reconstructor)
COPY . /app/

# Create timings directory for CSV files
RUN mkdir -p /app/timings

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash rest && \
    chown -R rest:rest /app && \
    chmod 777 /app/timings
USER rest

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV NEO4J_URI=bolt://localhost:7687
ENV NEO4J_USER=neo4j
ENV NEO4J_PWD=pwd
ENV ENABLE_MC_SIMILARITY=False
ENV OPENAI_API_KEY=
ENV HF_HUB_USERNAME=
ENV HF_HUB_TOKEN=
ENV GH_HUB_USERNAME=
ENV GH_HUB_TOKEN=

# Expose port for Flask REST API
EXPOSE 5002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5002/')" || exit 1

# Default command
CMD ["python", "legacy/legacy_server/server.py"]
