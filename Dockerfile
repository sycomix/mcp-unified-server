FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy entire project directory
COPY . .

# Install dependencies and the project itself
RUN pip install --no-cache-dir .


# Command to run the MCP server with stdio transport (default)
CMD ["mcp-unified-server"]
