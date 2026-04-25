# Use the official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Add a timestamp to invalidate cache
ARG CACHEBUST=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir gunicorn pg8000
RUN pip install --no-cache-dir -r requirements.txt


# Copy project files
COPY . .

# Expose port 8080 (Cloud Run default)
EXPOSE 8080

# Run the Flask app
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
