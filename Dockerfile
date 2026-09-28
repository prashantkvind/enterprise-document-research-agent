# Use official lightweight Python 3.10 image
FROM python:3.10-slim

# Prevent Python from writing bytecode and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set container working directory
WORKDIR /app

# Install necessary system build tools and PostgreSQL libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies file and install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy core service code, documents, and configuration
COPY config.py .
COPY agent_service.py .
COPY documents ./documents

# Expose FastAPI application port
EXPOSE 8000

# Container healthcheck for service monitoring
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run agent_service using uvicorn server
CMD ["uvicorn", "agent_service:app", "--host", "0.0.0.0", "--port", "8000"]
