# Use a lightweight base image with Python 3.11
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV ROLE=server

# Set working directory inside the container
WORKDIR /app

# Install system dependencies (git for cloning, build-essential for compiling tree-sitter bindings)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first for caching layers
COPY requirements.txt /app/

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY app /app/app
COPY static /app/static
COPY start.sh /app/

# Create the temporary data directory and give it write permissions
RUN mkdir -p /app/temp && chmod 777 /app/temp

# Make start.sh executable
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 8000

# Use start.sh as entrypoint
ENTRYPOINT ["/app/start.sh"]
