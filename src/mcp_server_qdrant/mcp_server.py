import json
import logging
from typing import Annotated, Any, List, Dict, Optional

from fastmcp import Context, FastMCP
from pydantic import Field
from qdrant_client import models

from mcp_server_qdrant.common.filters import make_indexes
from mcp_server_qdrant.common.func_tools import make_partial_function
from mcp_server_qdrant.common.wrap_filters import wrap_filters
from mcp_server_qdrant.embeddings.factory import create_embedding_provider
from mcp_server_qdrant.qdrant import ArbitraryFilter, Entry, Metadata, QdrantConnector
from mcp_server_qdrant.settings import (
    EmbeddingProviderSettings,
    QdrantSettings,
    ToolSettings,
)
from mcp_server_qdrant.task_manager import TaskManager
from mcp_server_qdrant.web_research_fixed import WebResearchManager
from mcp_server_qdrant.jetbrains_proxy import JetBrainsProxy

logger = logging.getLogger(__name__)


# FastMCP is an alternative interface for declaring the capabilities
# of the server. Its API is based on FastAPI.
class QdrantMCPServer(FastMCP):
    """
    A MCP server for Qdrant.
    """

    def __init__(
        self,
        tool_settings: ToolSettings,
        qdrant_settings: QdrantSettings,
        embedding_provider_settings: EmbeddingProviderSettings,
        name: str = "mcp-server-qdrant",
        instructions: str | None = None,
        **settings: Any,
    ):
        self.tool_settings = tool_settings
        self.qdrant_settings = qdrant_settings
        self.embedding_provider_settings = embedding_provider_settings

        self.embedding_provider = create_embedding_provider(embedding_provider_settings)
        self.qdrant_connector = QdrantConnector(
            qdrant_settings.location,
            qdrant_settings.api_key,
            qdrant_settings.collection_name,
            self.embedding_provider,
            qdrant_settings.local_path,
            make_indexes(qdrant_settings.filterable_fields_dict()),
        )
        self.task_manager = TaskManager() # Initialize TaskManager
        self.web_research_manager = WebResearchManager() # Initialize WebResearchManager
        self.jetbrains_proxy = JetBrainsProxy() # Initialize JetBrainsProxy

        super().__init__(name=name, instructions=instructions, **settings)

        self.setup_tools()
        self.setup_resources()
        asyncio.create_task(self.jetbrains_proxy.start_update_scheduler()) # Start the scheduler

    def format_entry(self, entry: Entry) -> str:
        """
        Feel free to override this method in your subclass to customize the format of the entry.
        """
        entry_metadata = json.dumps(entry.metadata) if entry.metadata else ""
        return f"<entry><content>{entry.content}</content><metadata>{entry_metadata}</metadata></entry>"

    def setup_tools(self):
        """
        Register the tools in the server.
        """

        async def store(
            ctx: Context,
            information: Annotated[str, Field(description="Text to store")],
            collection_name: Annotated[
                str, Field(description="The collection to store the information in")
            ],
            # The `metadata` parameter is defined as non-optional, but it can be None.
            # If we set it to be optional, some of the MCP clients, like Cursor,
            # cannot handle the optional parameter correctly.
            metadata: Annotated[
                Metadata | None,
                Field(
                    description="Extra metadata stored along with memorised information. Any json is accepted."
                ),
            ] = None,
        ) -> str:
            """
            Store some information in Qdrant.
            :param ctx: The context for the request.
            :param information: The information to store.
            :param metadata: JSON metadata to store with the information, optional.
            :param collection_name: The name of the collection to store the information in, optional. If not provided,
                                    the default collection is used.
            :return: A message indicating that the information was stored.
            """
            await ctx.debug(f"Storing information {information} in Qdrant")

            entry = Entry(content=information, metadata=metadata)

            await self.qdrant_connector.store(entry, collection_name=collection_name)
            if collection_name:
                return f"Remembered: {information} in collection {collection_name}"
            return f"Remembered: {information}"

        async def find(
            ctx: Context,
            query: Annotated[str, Field(description="What to search for")],
            collection_name: Annotated[
                str, Field(description="The collection to search in")
            ],
            query_filter: ArbitraryFilter | None = None,
        ) -> list[str]:
            """
            Find memories in Qdrant.
            :param ctx: The context for the request.
            :param query: The query to use for the search.
            :param collection_name: The name of the collection to search in, optional. If not provided,
                                    the default collection is used.
            :param query_filter: The filter to apply to the query.
            :return: A list of entries found.
            """

            # Log query_filter
            await ctx.debug(f"Query filter: {query_filter}")

            query_filter = models.Filter(**query_filter) if query_filter else None

            await ctx.debug(f"Finding results for query {query}")

            entries = await self.qdrant_connector.search(
                query,
                collection_name=collection_name,
                limit=self.qdrant_settings.search_limit,
                query_filter=query_filter,
            )
            if not entries:
                return [f"No information found for the query '{query}'"]
            content = [
                f"Results for the query '{query}'",
            ]
            for entry in entries:
                content.append(self.format_entry(entry))
            return content

        find_foo = find
        store_foo = store

        filterable_conditions = (
            self.qdrant_settings.filterable_fields_dict_with_conditions()
        )

        if len(filterable_conditions) > 0:
            find_foo = wrap_filters(find_foo, filterable_conditions)
        elif not self.qdrant_settings.allow_arbitrary_filter:
            find_foo = make_partial_function(find_foo, {"query_filter": None})

        if self.qdrant_settings.collection_name:
            find_foo = make_partial_function(
                find_foo, {"collection_name": self.qdrant_settings.collection_name}
            )
            store_foo = make_partial_function(
                store_foo, {"collection_name": self.qdrant_settings.collection_name}
            )

        self.tool(
            find_foo,
            name="qdrant-find",
            description=self.tool_settings.tool_find_description,
        )

        if not self.qdrant_settings.read_only:
            # Those methods can modify the database
            self.tool(
                store_foo,
                name="qdrant-store",
                description=self.tool_settings.tool_store_description,
            )

        # Task Manager Tools
        @self.tool(
            name="request_planning",
            description=(
                "Register a new user request and plan its associated tasks. You must provide 'originalRequest' and 'tasks', and optionally 'splitDetails'.\n\n" +
                "This tool initiates a new workflow for handling a user's request. The workflow is as follows:\n" +
                "1. Use 'request_planning' to register a request and its tasks.\n" +
                "2. After adding tasks, you MUST use 'get_next_task' to retrieve the first task. A progress table will be displayed.\n" +
                "3. Use 'get_next_task' to retrieve the next uncompleted task.\n" +
                "4. **IMPORTANT:** After marking a task as done, the assistant MUST NOT proceed to another task without the user's approval. The user must explicitly approve the completed task using 'approve_task_completion'. A progress table will be displayed before each approval request.\n" +
                "5. Once a task is approved, you can proceed to 'get_next_task' again to fetch the next pending task.\n" +
                "6. Repeat this cycle until all tasks are done.\n" +
                "7. After all tasks are completed (and approved), 'get_next_task' will indicate that all tasks are done and that the request awaits approval for full completion.\n" +
                "8. The user must then approve the entire request's completion using 'approve_request_completion'. If the user does not approve and wants more tasks, you can again use 'request_planning' to add new tasks and continue the cycle.\n\n" +
                "The critical point is to always wait for user approval after completing each task and after all tasks are done, wait for request completion approval. Do not proceed automatically."
            )
        )
        async def request_planning(
            ctx: Context,
            originalRequest: Annotated[str, Field(description="The original request from the user.")],
            tasks: Annotated[List[Dict[str, str]], Field(description="A list of tasks, each with a title and description.")],
            splitDetails: Annotated[Optional[str], Field(description="Details about how the request was split into tasks.")] = None,
        ) -> Dict[str, Any]:
            return self.task_manager.request_planning(originalRequest, tasks, splitDetails)

        @self.tool(
            name="get_next_task",
            description=(
                "Given a 'requestId', return the next pending task (not done yet). If all tasks are completed, it will indicate that no more tasks are left and that you must wait for the request completion approval.\n\n" +
                "A progress table showing the current status of all tasks will be displayed with each response.\n\n" +
                "If the same task is returned again or if no new task is provided after a task was marked as done but not yet approved, you MUST NOT proceed. In such a scenario, you must prompt the user for approval via 'approve_task_completion' before calling 'get_next_task' again. Do not skip the user's approval step.\n" +
                "In other words:\n" +
                "- After calling 'mark_task_done', do not call 'get_next_task' again until 'approve_task_completion' is called by the user.\n" +
                "- If 'get_next_task' returns 'all_tasks_done', it means all tasks have been completed. At this point, you must not start a new request or do anything else until the user decides to 'approve_request_completion' or possibly add more tasks via 'request_planning'."
            )
        )
        async def get_next_task(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
        ) -> Dict[str, Any]:
            return self.task_manager.get_next_task(requestId)

        @self.tool(
            name="mark_task_done",
            description=(
                "Mark a given task as done after you've completed it. Provide 'requestId' and 'taskId', and optionally 'completedDetails'.\n\n" +
                "After marking a task as done, a progress table will be displayed showing the updated status of all tasks.\n\n" +
                "After this, DO NOT proceed to 'get_next_task' again until the user has explicitly approved this completed task using 'approve_task_completion'."
            )
        )
        async def mark_task_done(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
            taskId: Annotated[str, Field(description="The ID of the task.")],
            completedDetails: Annotated[Optional[str], Field(description="Details about the completion.")] = None,
        ) -> Dict[str, Any]:
            return self.task_manager.mark_task_done(requestId, taskId, completedDetails)

        @self.tool(
            name="approve_task_completion",
            description=(
                "Once the assistant has marked a task as done using 'mark_task_done', the user must call this tool to approve that the task is genuinely completed. Only after this approval can you proceed to 'get_next_task' to move on.\n\n" +
                "A progress table will be displayed before requesting approval, showing the current status of all tasks.\n\n" +
                "If the user does not approve, do not call 'get_next_task'. Instead, the user may request changes, or even re-plan tasks by using 'request_planning' again."
            )
        )
        async def approve_task_completion(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
            taskId: Annotated[str, Field(description="The ID of the task.")],
        ) -> Dict[str, Any]:
            return self.task_manager.approve_task_completion(requestId, taskId)

        @self.tool(
            name="approve_request_completion",
            description=(
                "After all tasks are done and approved, this tool finalizes the entire request. The user must call this to confirm that the request is fully completed.\n\n" +
                "A progress table showing the final status of all tasks will be displayed before requesting final approval.\n\n" +
                "If not approved, the user can add new tasks using 'request_planning' and continue the process."
            )
        )
        async def approve_request_completion(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
        ) -> Dict[str, Any]:
            return self.task_manager.approve_request_completion(requestId)

        @self.tool(
            name="open_task_details",
            description=(
                "Get details of a specific task by 'taskId'. This is for inspecting task information at any point."
            )
        )
        async def open_task_details(
            ctx: Context,
            taskId: Annotated[str, Field(description="The ID of the task.")],
        ) -> Dict[str, Any]:
            return self.task_manager.open_task_details(taskId)

        @self.tool(
            name="list_requests",
            description=(
                "List all requests with their basic information and summary of tasks. This provides a quick overview of all requests in the system."
            )
        )
        async def list_requests(
            ctx: Context,
        ) -> Dict[str, Any]:
            return self.task_manager.list_requests()

        @self.tool(
            name="add_tasks_to_request",
            description=(
                "Add new tasks to an existing request. This allows extending a request with additional tasks.\n\n" +
                "A progress table will be displayed showing all tasks including the newly added ones."
            )
        )
        async def add_tasks_to_request(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
            tasks: Annotated[List[Dict[str, str]], Field(description="A list of tasks, each with a title and description.")],
        ) -> Dict[str, Any]:
            return self.task_manager.add_tasks_to_request(requestId, tasks)

        @self.tool(
            name="update_task",
            description=(
                "Update an existing task's title and/or description. Only uncompleted tasks can be updated.\n\n" +
                "A progress table will be displayed showing the updated task information."
            )
        )
        async def update_task(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
            taskId: Annotated[str, Field(description="The ID of the task.")],
            updates: Annotated[Dict[str, str], Field(description="A dictionary containing the fields to update (title and/or description).")],
        ) -> Dict[str, Any]:
            return self.task_manager.update_task(requestId, taskId, updates)

        @self.tool(
            name="delete_task",
            description=(
                "Delete a specific task from a request. Only uncompleted tasks can be deleted.\n\n" +
                "A progress table will be displayed showing the remaining tasks after deletion."
            )
        )
        async def delete_task(
            ctx: Context,
            requestId: Annotated[str, Field(description="The ID of the request.")],
            taskId: Annotated[str, Field(description="The ID of the task.")],
        ) -> Dict[str, Any]:
            return self.task_manager.delete_task(requestId, taskId)

        # Web Research Tools
        @self.tool(
            name="search_google",
            description="Search Google for a query."
        )
        async def search_google(
            ctx: Context,
            query: Annotated[str, Field(description="The search query.")],
        ) -> Dict[str, Any]:
            return await self.web_research_manager.search_google(query)

        @self.tool(
            name="visit_page",
            description="Visit a webpage and extract its content."
        )
        async def visit_page(
            ctx: Context,
            url: Annotated[str, Field(description="The URL to visit.")],
            takeScreenshot: Annotated[bool, Field(description="Whether to take a screenshot.")] = False,
        ) -> Dict[str, Any]:
            return await self.web_research_manager.visit_page(url, takeScreenshot)

        @self.tool(
            name="take_screenshot",
            description="Take a screenshot of the current page."
        )
        async def take_screenshot(
            ctx: Context,
        ) -> Dict[str, Any]:
            return await self.web_research_manager.take_screenshot()

        # JetBrains Proxy Tools
        @self.tool(
            name="jetbrains_list_tools",
            description="List available tools from the connected JetBrains IDE."
        )
        async def jetbrains_list_tools(
            ctx: Context,
        ) -> Dict[str, Any]:
            return await self.jetbrains_proxy.list_tools()

        @self.tool(
            name="jetbrains_call_tool",
            description="Call a specific tool in the connected JetBrains IDE."
        )
        async def jetbrains_call_tool(
            ctx: Context,
            tool_name: Annotated[str, Field(description="The name of the tool to call.")],
            tool_args: Annotated[Dict[str, Any], Field(description="Arguments for the tool call.")] = {},
        ) -> Dict[str, Any]:
            return await self.jetbrains_proxy.call_tool(tool_name, tool_args)

    def setup_resources(self):
        @self.resource(
            uri_pattern="research://current/summary",
            name="Current Research Session Summary",
            description="Summary of the current research session including queries and results",
            mime_type="application/json"
        )
        async def get_research_summary(ctx: Context) -> Dict[str, Any]:
            return self.web_research_manager.get_current_session_summary()

        @self.resource(
            uri_pattern="research://screenshots/{index}",
            name="Screenshot",
            description="Screenshot taken during web research",
            mime_type="image/png"
        )
        async def get_research_screenshot(ctx: Context, index: int) -> bytes:
            return self.web_research_manager.get_screenshot_data(index)

    async def on_shutdown(self):
        await self.web_research_manager.cleanup()
        await self.jetbrains_proxy.close()

