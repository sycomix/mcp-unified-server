import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class JetBrainsProxy:
    def __init__(self, host: str = "127.0.0.1"):
        self.host = host
        self.cached_endpoint: Optional[str] = None
        self.previous_response: Optional[str] = None
        self.update_task: Optional[asyncio.Task] = None

    async def _test_list_tools(self, endpoint: str) -> bool:
        logger.info(f"Sending test request to {endpoint}/mcp/list_tools")
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{endpoint}/mcp/list_tools")
                res.raise_for_status()

                current_response = res.text
                logger.info(f"Received response from {endpoint}/mcp/list_tools: {current_response[:100]}...")

                if self.previous_response is not None and self.previous_response != current_response:
                    logger.info("Response has changed since the last check.")
                    # TODO: Send tools changed notification via FastMCP
                self.previous_response = current_response
                return True
        except httpx.RequestError as e:
            logger.error(f"Error during _test_list_tools for endpoint {endpoint}: {e}")
            return False

    async def _find_working_ide_endpoint(self) -> str:
        logger.info("Attempting to find a working IDE endpoint...")

        if os.getenv("IDE_PORT"):
            logger.info(f"IDE_PORT is set to {os.getenv("IDE_PORT")}. Testing this port.")
            test_endpoint = f"http://{self.host}:{os.getenv("IDE_PORT")}/api"
            if await self._test_list_tools(test_endpoint):
                logger.info(f"IDE_PORT {os.getenv("IDE_PORT")} is working.")
                return test_endpoint
            else:
                raise Exception(f"Specified IDE_PORT={os.getenv("IDE_PORT")} but it is not responding correctly.")

        if self.cached_endpoint and await self._test_list_tools(self.cached_endpoint):
            logger.info('Using cached endpoint, it\'s still working')
            return self.cached_endpoint

        for port in range(63342, 63353):
            candidate_endpoint = f"http://{self.host}:{port}/api"
            logger.info(f"Testing port {port}...")
            is_working = await self._test_list_tools(candidate_endpoint)
            if is_working:
                logger.info(f"Found working IDE endpoint at {candidate_endpoint}")
                return candidate_endpoint
            else:
                logger.info(f"Port {port} is not responding correctly.")

        self.previous_response = ""
        logger.info("No working IDE endpoint found in range 63342-63352")
        raise Exception("No working IDE endpoint found in range 63342-63352")

    async def update_ide_endpoint(self):
        try:
            self.cached_endpoint = await self._find_working_ide_endpoint()
            logger.info(f"Updated cached_endpoint to: {self.cached_endpoint}")
        except Exception as e:
            logger.error(f"Failed to update IDE endpoint: {e}")

    async def start_update_scheduler(self):
        if self.update_task:
            self.update_task.cancel()
        self.update_task = asyncio.create_task(self._update_loop())

    async def _update_loop(self):
        await self.update_ide_endpoint()
        while True:
            await asyncio.sleep(10)  # Check every 10 seconds
            await self.update_ide_endpoint()

    async def list_tools(self) -> Dict[str, Any]:
        if not self.cached_endpoint:
            raise Exception("No working IDE endpoint available.")
        try:
            async with httpx.AsyncClient() as client:
                tools_response = await client.get(f"{self.cached_endpoint}/mcp/list_tools")
                tools_response.raise_for_status()
                tools = tools_response.json()
                logger.info(f"Successfully fetched tools: {json.dumps(tools)}")
                return {"tools": tools}
        except httpx.RequestError as e:
            logger.error(f"Error handling ListToolsRequestSchema request: {e}")
            raise Exception(f"Unable to list tools: {e}")

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Handling tool call: name={name}, args={json.dumps(args)}")
        if not self.cached_endpoint:
            raise Exception("No working IDE endpoint available.")

        try:
            logger.info(f"ENDPOINT: {self.cached_endpoint} | Tool name: {name} | args: {json.dumps(args)}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.cached_endpoint}/mcp/{name}",
                    headers={
                        "Content-Type": "application/json",
                    },
                    json=args,
                )
                response.raise_for_status()

                ide_response = response.json()
                logger.info(f"Parsed response: {ide_response}")

                is_error = bool(ide_response.get("error"))
                text = ide_response.get("status") or ide_response.get("error")

                return {
                    "content": [{"type": "text", "text": text}],
                    "isError": is_error,
                }
        except httpx.RequestError as e:
            logger.error(f"Error in handleToolCall: {e}")
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            }

    async def close(self):
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
