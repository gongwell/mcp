import httpx
from typing import Any, Dict
import asyncio
import json
import os
from mcp import StdioServer, ToolCallResult, tool

# Attempt to import FastMCP from the expected location
try:
    from mcp.server.fastmcp.server import FastMCP
except ImportError:
    print("Warning: mcp.server.fastmcp.server.FastMCP not found. Using a dummy placeholder.")
    print("Please ensure your MCP framework is installed and the import path is correct.")
    class FastMCP:
        def __init__(self, host="0.0.0.0", port=8000):
            self.host = host
            self.port = port
            print(f"Dummy FastMCP initialized on {self.host}:{self.port}")

        def tool(self):
            def decorator(func):
                return func
            return decorator
        
        def run(self):
            print(f"Dummy FastMCP run method called. In a real scenario, this would start the server.")
            async def run_main_test():
                await main()
            print("Dummy FastMCP is 'running' the test main function.")
            asyncio.run(run_main_test())

# Instantiate the server object
mcp = FastMCP(host="0.0.0.0", port=8000)

# Azure Content Understanding API configuration
AZURE_ENDPOINT = "https://understanding207171416216.cognitiveservices.azure.com/"
AZURE_ANALYZER_ID = "myfirsyVideo"
AZURE_API_KEY = ""
API_VERSION = "2024-12-01-preview"
USER_AGENT = "MCPContentUnderstandingClient/1.0"

async def azure_content_request(method: str, url: str, data: Any = None) -> Dict[str, Any] | str:
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }
    async with httpx.AsyncClient() as client:
        try:
            if method == "PUT":
                response = await client.put(url, headers=headers, json=data, timeout=60.0)
            elif method == "GET":
                response = await client.get(url, headers=headers, timeout=60.0)
            else:
                return f"Unsupported HTTP method: {method}"
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as e:
            return f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        except Exception as e:
            return f"An error occurred: {str(e)}"

@mcp.tool()
async def create_or_update_analyzer(request_body: dict = None) -> Dict[str, Any] | str:
    """
    创建或更新自定义分析器。request_body为分析器配置（如无则用默认示例）。
    """
    url = f"{AZURE_ENDPOINT}contentunderstanding/analyzers/{AZURE_ANALYZER_ID}?api-version={API_VERSION}"
    if request_body is None:
        request_body = {
            "description": "Sample marketing video analyzer",
            "scenario": "videoShot",
            "config": {"disableContentFiltering": True},
            "fieldSchema": {
                "fields": {
                    "Description": {
                        "type": "string",
                        "description": "Detailed summary of the video segment, focusing on product characteristics, lighting, and color palette."
                    },
                    "Sentiment": {
                        "type": "string",
                        "method": "classify",
                        "enum": ["Positive", "Neutral", "Negative"]
                    }
                }
            }
        }
    return await azure_content_request("PUT", url, data=request_body)

@mcp.tool()
async def get_operation_status(operation_id: str) -> Dict[str, Any] | str:
    """
    查询分析器操作状态。operation_id为创建/更新分析器时返回的operationId。
    """
    url = f"{AZURE_ENDPOINT}contentunderstanding/analyzers/{AZURE_ANALYZER_ID}/operations/{operation_id}?api-version={API_VERSION}"
    return await azure_content_request("GET", url)

@mcp.tool()
async def get_analysis_result(result_id: str) -> Dict[str, Any] | str:
    """
    获取分析结果。result_id为分析请求返回的resultId。
    """
    url = f"{AZURE_ENDPOINT}contentunderstanding/analyzers/{AZURE_ANALYZER_ID}/results/{result_id}?api-version={API_VERSION}"
    return await azure_content_request("GET", url)

# --- Tool Definitions ---

@tool(
    name="analyze_local_video",
    description="Analyzes a video file stored locally and returns a description and tags.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The absolute local path to the video file to be analyzed."
            }
        },
        "required": ["file_path"]
    }
)
async def analyze_local_video(file_path: str) -> ToolCallResult:
    print(f"[ContentUnderstandingServer] Received request to analyze video at: {file_path}")
    if not os.path.exists(file_path):
        print(f"[ContentUnderstandingServer] Error: File not found at {file_path}")
        return ToolCallResult(
            is_error=True,
            content={"error": "File not found", "file_path": file_path}
        )
    
    if not os.path.isfile(file_path):
        print(f"[ContentUnderstandingServer] Error: Path is not a file: {file_path}")
        return ToolCallResult(
            is_error=True,
            content={"error": "Path is not a file", "file_path": file_path}
        )

    # Simulate video analysis
    await asyncio.sleep(1) # Simulate processing time
    
    file_name = os.path.basename(file_path)
    simulated_analysis = {
        "file_name": file_name,
        "description": f"This is a simulated analysis of the video '{file_name}'. It appears to be a video about interesting content.",
        "tags": ["simulated", "video", "analysis", "interesting"],
        "duration_seconds": 15, # Simulated
        "resolution": "1920x1080" # Simulated
    }
    print(f"[ContentUnderstandingServer] Successfully analyzed video: {file_path}. Analysis: {simulated_analysis}")
    return ToolCallResult(content=simulated_analysis)

# --- Main Server Logic ---

async def main():
    server = StdioServer()
    server.register_tool(analyze_local_video)
    print("[ContentUnderstandingServer] Content Understanding MCP Server started. Registered tools: analyze_local_video")
    print("[ContentUnderstandingServer] Waiting for tool calls via MCP protocol...")
    await server.run()

if __name__ == "__main__":
    asyncio.run(main()) 