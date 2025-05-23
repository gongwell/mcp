import httpx
import os
import asyncio

try:
    from mcp.server.fastmcp.server import FastMCP
except ImportError:
    print("Warning: mcp.server.fastmcp.server.FastMCP not found. Using a dummy placeholder.")
    class FastMCP:
        def __init__(self, host="0.0.0.0", port=8001):
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

mcp = FastMCP(host="0.0.0.0", port=8001)

@mcp.tool()
async def download_video_by_url(play_url: str) -> dict:
    """
    通过视频直链下载视频到本地并返回本地路径
    """
    TEMP_VIDEO_DOWNLOAD_DIR = "/tmp/mcp_video_downloads"
    if not play_url or not isinstance(play_url, str):
        return {"error": "Invalid play_url"}
    if not os.path.exists(TEMP_VIDEO_DOWNLOAD_DIR):
        os.makedirs(TEMP_VIDEO_DOWNLOAD_DIR)
    filename = play_url.split("/")[-1].split("?")[0]
    if not filename.endswith(".mp4"):
        filename += ".mp4"
    local_path = os.path.join(TEMP_VIDEO_DOWNLOAD_DIR, filename)
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(play_url)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
    except Exception as e:
        return {"error": f"Failed to download video: {str(e)}"}
    return {"file_path": local_path}

async def main():
    # Example usage
    url = "https://example.com/video.mp4"
    result = await download_video_by_url(url)
    print(result)

if __name__ == "__main__":
    mcp.run() 