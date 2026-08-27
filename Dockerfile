# Use minimal Python alpine image for smaller size
FROM python:3.11-alpine3.20

# Set working directory
WORKDIR /app

# git: needed to pip install from GitHub. ttf-dejavu: the font the dashboard
# renderer draws with (Pillow ships no fonts of its own).
RUN apk add --no-cache git ttf-dejavu

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application: every module, the web UI and the icon assets.
# Copying *.py rather than naming files keeps a new module from being left out.
COPY *.py ./
COPY web/ ./web/
COPY assets/ ./assets/

# Create directories for artwork and tokens
RUN mkdir -p /artwork /tokens /templates /config

# Web UI
EXPOSE 8080

# Make script executable
RUN chmod +x sync_artwork.py

# Run the sync script
CMD ["python", "-u", "sync_artwork.py"]
