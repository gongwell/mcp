import httpx
from typing import Any, Dict
import asyncio
import os

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

TIKTOK_API_KEY = ""
TIKTOK_API_HOST = "tiktok-api23.p.rapidapi.com"
TIKTOK_API_BASE_URL = "https://tiktok-api23.p.rapidapi.com"
USER_AGENT = "MCPTiktokClient/1.0"

async def make_tiktok_request(endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any] | str:
    headers = {
        "x-rapidapi-key": TIKTOK_API_KEY,
        "x-rapidapi-host": TIKTOK_API_HOST,
        "User-Agent": USER_AGENT
    }
    url = f"{TIKTOK_API_BASE_URL}/{endpoint}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        except Exception as e:
            return f"An error occurred: {str(e)}"

@mcp.tool()
async def get_user_info(uniqueId: str) -> Dict[str, Any] | str:
    """
    获取用户信息
    """
    params = {"uniqueId": uniqueId}
    return await make_tiktok_request("api/user/info", params)

@mcp.tool()
async def get_user_info_with_region(uniqueId: str) -> Dict[str, Any] | str:
    """
    获取用户信息（包括用户区域）
    """
    params = {"uniqueId": uniqueId}
    return await make_tiktok_request("api/user/info-with-region", params)

@mcp.tool()
async def get_user_info_by_id(userId: str) -> Dict[str, Any] | str:
    """
    按ID获取用户信息
    """
    params = {"userId": userId}
    return await make_tiktok_request("api/user/info-by-id", params)

@mcp.tool()
async def get_user_followers(secUid: str, count: int = 30, minCursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户关注者
    """
    params = {"secUid": secUid, "count": count, "minCursor": minCursor}
    return await make_tiktok_request("api/user/followers", params)

@mcp.tool()
async def get_user_followings(secUid: str, count: int = 30, minCursor: int = 0, maxCursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户关注
    """
    params = {"secUid": secUid, "count": count, "minCursor": minCursor, "maxCursor": maxCursor}
    return await make_tiktok_request("api/user/followings", params)

@mcp.tool()
async def get_user_posts(secUid: str, count: int = 35, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户帖子
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/posts", params)

@mcp.tool()
async def get_user_popular_posts(secUid: str, count: int = 35, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户热门文章
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/popular-posts", params)

@mcp.tool()
async def get_user_oldest_posts(secUid: str, count: int = 30, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户最早的帖子
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/oldest-posts", params)

@mcp.tool()
async def get_user_liked_posts(secUid: str, count: int = 30, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户最喜欢帖子
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/liked-posts", params)

@mcp.tool()
async def get_user_playlist(secUid: str, count: int = 20, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户播放列表
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/playlist", params)

@mcp.tool()
async def get_user_repost(secUid: str, count: int = 30, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取用户重新发布
    """
    params = {"secUid": secUid, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/user/repost", params)

@mcp.tool()
async def search_general(keyword: str, cursor: int = 0, search_id: int = 0) -> Dict[str, Any] | str:
    """
    搜索常规（顶部）
    """
    params = {"keyword": keyword, "cursor": cursor, "search_id": search_id}
    return await make_tiktok_request("api/search/general", params)

@mcp.tool()
async def search_video(keyword: str, cursor: int = 0, search_id: int = 0) -> Dict[str, Any] | str:
    """
    搜索视频
    """
    params = {"keyword": keyword, "cursor": cursor, "search_id": search_id}
    return await make_tiktok_request("api/search/video", params)

@mcp.tool()
async def search_account(keyword: str, cursor: int = 0, search_id: int = 0) -> Dict[str, Any] | str:
    """
    搜索账户
    """
    params = {"keyword": keyword, "cursor": cursor, "search_id": search_id}
    return await make_tiktok_request("api/search/account", params)

@mcp.tool()
async def search_live(keyword: str, cursor: int = 0, search_id: int = 0) -> Dict[str, Any] | str:
    """
    搜索Live
    """
    params = {"keyword": keyword, "cursor": cursor, "search_id": search_id}
    return await make_tiktok_request("api/search/account", params)

@mcp.tool()
async def get_post_detail(videoId: str) -> Dict[str, Any] | str:
    """
    获取文章详细信息
    """
    params = {"videoId": videoId}
    return await make_tiktok_request("api/post/detail", params)

@mcp.tool()
async def get_post_comments(videoId: str, count: int = 50, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取帖子的评论
    """
    params = {"videoId": videoId, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/post/comments", params)

@mcp.tool()
async def get_post_comment_replies(videoId: str, commentId: str, count: int = 6, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取帖子的回复评论
    """
    params = {"videoId": videoId, "commentId": commentId, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/post/comment/replies", params)

@mcp.tool()
async def get_post_related(videoId: str, count: int = 16, cursor: int = 0) -> Dict[str, Any] | str:
    """
    获取相关文章
    """
    params = {"videoId": videoId, "count": count, "cursor": cursor}
    return await make_tiktok_request("api/post/related", params)

@mcp.tool()
async def get_post_trending(count: int = 16) -> Dict[str, Any] | str:
    """
    获取热点文章
    """
    params = {"count": count}
    return await make_tiktok_request("api/post/trending", params)

@mcp.tool()
async def download_video(url: str) -> Dict[str, Any] | str:
    """
    下载视频到本地并返回本地路径
    """
    TEMP_VIDEO_DOWNLOAD_DIR = "/tmp/mcp_video_downloads"
    # 1. 调用 TikTok API 拿到视频直链
    params = {"url": url}
    api_result = await make_tiktok_request("api/download/video", params)
    if not isinstance(api_result, dict):
        return {"error": f"Failed to get video download info: {api_result}"}
    # 2. 获取 play 字段
    play_url = api_result.get("data", {}).get("play")
    if not play_url:
        return {"error": "No play url found in TikTok API response."}
    # 3. 下载到本地
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
    # 4. 只返回本地路径
    return {"file_path": local_path}

@mcp.tool()
async def get_video_download_url(url: str) -> dict:
    """
    获取 TikTok 视频的下载直链（play/play_watermark），不下载
    """
    params = {"url": url}
    api_result = await make_tiktok_request("api/download/video", params)
    # 兼容不同返回结构
    data = api_result.get("data", api_result)
    return {
        "play": data.get("play"),
        "play_watermark": data.get("play_watermark")
    }

@mcp.tool()
async def download_video_by_url(play_url: str) -> dict:
    """
    通过视频直链下载视频到本地并返回本地路径
    """
    TEMP_VIDEO_DOWNLOAD_DIR = "/tmp/mcp_video_downloads"
    import os
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
    result = await get_user_info("taylorswift")
    print(result)

if __name__ == "__main__":
    mcp.run() 