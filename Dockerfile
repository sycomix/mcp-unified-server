FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy entire project directory
COPY . .

# Install dependencies and the project itself
RUN pip install --no-cache-dir .

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the application using uvicorn
CMD ["python", "-m", "uvicorn", "mcp_server_qdrant.server:app", "--host", "0.0.0.0", "--port", "8000"]
