# Unified MCP Tool Server

This project combines various Model Context Protocol (MCP) server functionalities into a single, unified server. It provides:

-   **Qdrant Memory Management**: Store and retrieve information from a Qdrant vector database.
-   **Task Management**: Tools for creating, tracking, and managing tasks.
-   **Web Research**: Capabilities to search Google, visit web pages, extract content, and take screenshots.
-   **JetBrains IDE Proxy**: A bridge to interact with a running JetBrains IDE's MCP server.

## Installation

Follow these steps to set up and run the Unified MCP Tool Server.

### Prerequisites

-   Python 3.10 or higher
-   `uv` (a fast Python package installer and resolver)
-   `playwright` browsers

### Steps

1.  **Navigate to the project directory**:
    ```bash
    cd E:\MCP-Experiments\mcp-unified-server
    ```

2.  **Install dependencies using `uv`**:
    ```bash
    uv sync
    ```

3.  **Install Playwright browsers**:
    ```bash
    python -m playwright install
    ```

4.  **Install the project in editable mode**:
    This makes the `mcp_server_qdrant` module discoverable by the Python interpreter.
    ```bash
    uv pip install -e .
    ```

## Configuration

The server's behavior can be configured using environment variables.

### Qdrant Configuration

These variables configure the connection to your Qdrant instance.

| Name                     | Description                                                         | Default Value                                                     |
| :----------------------- | :------------------------------------------------------------------ | :---------------------------------------------------------------- |
| `QDRANT_URL`             | URL of the Qdrant server                                            | `None`                                                            |
| `QDRANT_API_KEY`         | API key for the Qdrant server                                       | `None`                                                            |
| `COLLECTION_NAME`        | Name of the default collection to use.                              | `None`                                                            |
| `QDRANT_LOCAL_PATH`      | Path to the local Qdrant database (alternative to `QDRANT_URL`)     | `None`                                                            |
| `EMBEDDING_PROVIDER`     | Embedding provider to use (currently only "fastembed" is supported) | `fastembed`                                                       |
| `EMBEDDING_MODEL`        | Name of the embedding model to use                                  | `sentence-transformers/all-MiniLM-L6-v2`                          |
| `TOOL_STORE_DESCRIPTION` | Custom description for the store tool                               | See default in `src/mcp_server_qdrant/settings.py`                |
| `TOOL_FIND_DESCRIPTION`  | Custom description for the find tool                                | See default in `src/mcp_server_qdrant/settings.py`                |

**Note**: You cannot provide both `QDRANT_URL` and `QDRANT_LOCAL_PATH` at the same time.

### JetBrains Proxy Configuration

| Name      | Description                                     | Default Value |
| :-------- | :---------------------------------------------- | :------------ |
| `IDE_PORT`| The port of the running JetBrains IDE's MCP server. | Scans `63342-63352` |

### Example Environment Variable Setup (Linux/macOS)

```bash
export QDRANT_URL="http://localhost:6333"
export COLLECTION_NAME="my-unified-collection"
export IDE_PORT="63342" # If your IDE is running on a specific port
```

### Example Environment Variable Setup (Windows - Command Prompt)

```cmd
set QDRANT_URL=http://localhost:6333
set COLLECTION_NAME=my-unified-collection
set IDE_PORT=63342
```

### Example Environment Variable Setup (Windows - PowerShell)

```powershell
$env:QDRANT_URL="http://localhost:6333"
$env:COLLECTION_NAME="my-unified-collection"
$env:IDE_PORT="63342"
```

## Usage

To run the unified server, navigate to the project directory and execute:

```bash
python -m mcp_server_qdrant.main
```

The server will start and listen for MCP client connections via `stdio` by default.

### Connecting MCP Clients

Configure your MCP-compatible client (e.g., Cursor, Claude Desktop) to connect to this server. The default transport is `stdio`.

### Available Tools and Resources

Once connected, your MCP client will have access to the following tools and resources:

-   **Qdrant Tools**: `qdrant-find`, `qdrant-store`
-   **Task Management Tools**: `request_planning`, `get_next_task`, `mark_task_done`, `approve_task_completion`, `approve_request_completion`, `open_task_details`, `list_requests`, `add_tasks_to_request`, `update_task`, `delete_task`
-   **Web Research Tools**: `search_google`, `visit_page`, `take_screenshot`
-   **JetBrains Proxy Tools**: `jetbrains_list_tools`, `jetbrains_call_tool`
-   **Web Research Resources**: `research://current/summary`, `research://screenshots/{index}`

## Contributing

Contributions are welcome! If you have suggestions for how this unified server could be improved, or want to report a bug, please open an issue.

## License

This project is licensed under the Apache License 2.0.
