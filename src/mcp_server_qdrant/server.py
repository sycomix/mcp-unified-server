from mcp_server_qdrant.mcp_server import QdrantMCPServer
from mcp_server_qdrant.settings import (
    EmbeddingProviderSettings,
    QdrantSettings,
    ToolSettings,
)

mcp_server = QdrantMCPServer(
    tool_settings=ToolSettings(),
    qdrant_settings=QdrantSettings(),
    embedding_provider_settings=EmbeddingProviderSettings(),
)

# For ASGI compatibility (uvicorn, etc.)
app = mcp_server.http_app()

# Keep the original mcp variable for backward compatibility
mcp = mcp_server
