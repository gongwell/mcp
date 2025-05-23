import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Optional
from contextlib import AsyncExitStack, asynccontextmanager
import os
import traceback
import json
import hashlib
import httpx

from openai import OpenAI

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import redis.asyncio as aioredis

# --- Constants & Configurations ---
REDIS_HOST = "localhost"
REDIS_PORT = 6379
OPENAI_API_KEY = ""
MCP_SERVER_SCRIPT_TWITTER = "/home/ubuntu/twmcp/twitter_mcp_server.py"
MCP_SERVER_SCRIPT_TIKTOK = "/home/ubuntu/twmcp/tiktok_mcp_server.py"
MCP_SERVER_SCRIPT_LINKEDIN = "/home/ubuntu/twmcp/linkedin_mcp_server.py"
MCP_SERVER_SCRIPT_CONTENT_UNDERSTANDING = "/home/ubuntu/twmcp/contentunderstanding_mcp_server.py"
MCP_SERVER_SCRIPT_VIDEO_DOWNLOAD = "/home/ubuntu/twmcp/video_download_mcp_server.py"
TEMP_VIDEO_DOWNLOAD_DIR = "/tmp/mcp_video_downloads"

# --- Global Variables ---
redis_client: Optional[aioredis.Redis] = None
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- FastAPI Lifespan for Redis Connection Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    print("Attempting to connect to Redis...")
    try:
        redis_client = aioredis.from_url(
            f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping()
        print(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}.")
    except Exception as e:
        print(f"Could not connect to Redis: {e}. Proceeding without Redis history.")
        redis_client = None
    
    # Ensure the temporary video download directory exists
    if not os.path.exists(TEMP_VIDEO_DOWNLOAD_DIR):
        try:
            os.makedirs(TEMP_VIDEO_DOWNLOAD_DIR)
            print(f"Created temporary video download directory: {TEMP_VIDEO_DOWNLOAD_DIR}")
        except Exception as e:
            print(f"Error creating temporary video download directory {TEMP_VIDEO_DOWNLOAD_DIR}: {e}")
            # Depending on requirements, you might want to raise an error here or handle it differently
    
    yield
    
    if redis_client:
        print("Closing Redis connection...")
        await redis_client.close()
        print("Redis connection closed.")

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MCP Client API - Twitter, TikTok & LinkedIn Agent",
    version="0.5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MCP Server Script Configuration ---
MCP_SERVER_SCRIPTS = {
    "twitter": MCP_SERVER_SCRIPT_TWITTER,
    "tiktok": MCP_SERVER_SCRIPT_TIKTOK,
    "linkedin": MCP_SERVER_SCRIPT_LINKEDIN,
    "contentunderstanding": MCP_SERVER_SCRIPT_CONTENT_UNDERSTANDING,
    "video_download": MCP_SERVER_SCRIPT_VIDEO_DOWNLOAD,
}

# --- Helper Functions ---
async def call_mcp_tool_via_protocol(platform: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    server_script_path = MCP_SERVER_SCRIPTS.get(platform.lower())
    if not server_script_path:
        raise HTTPException(status_code=404, detail=f"MCP server script for platform '{platform}' not configured.")

    if not os.path.exists(server_script_path):
        raise HTTPException(status_code=500, detail=f"MCP server script not found at path: {server_script_path}")

    print(f"[MCP_REQUEST_LOG] Platform: {platform}, Tool: {tool_name}, Params: {params}")

    command = "python"
    server_params = StdioServerParameters(
        command=command,
        args=[server_script_path],
    )

    mcp_tool_result_content = None

    try:
        async with AsyncExitStack() as exit_stack:
            stdio_transport_manager = stdio_client(server_params)
            stdio_transport = await exit_stack.enter_async_context(stdio_transport_manager)
            stdio_reader, stdio_writer = stdio_transport

            async with ClientSession(stdio_reader, stdio_writer) as session:
                await session.initialize()
                tool_result = await session.call_tool(tool_name, params)
                if hasattr(tool_result, 'content'):
                    mcp_tool_result_content = tool_result.content
                else:
                    mcp_tool_result_content = {"raw_result": str(tool_result)}
        
        return mcp_tool_result_content

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Command '{command}' not found. Ensure it's in PATH.")
    except ConnectionRefusedError:
        raise HTTPException(status_code=503, detail=f"Failed to connect to MCP server for {platform} at {server_script_path}.")
    except RuntimeError as e:
        print(f"MCP Runtime error for {platform} ({tool_name}): {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"MCP client runtime error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error calling MCP service {platform} ({tool_name}): {type(e).__name__} - {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# --- 自动补全TikTok视频下载和分析链路 ---
async def auto_chain_tiktok_video_analysis(results_dict):
    # 查找play_url
    play_url = None
    file_path = None
    for v in results_dict.values():
        if isinstance(v, dict):
            if v.get("play"):
                play_url = v["play"]
            if v.get("play_url"):
                play_url = v["play_url"]
            if v.get("file_path"):
                file_path = v["file_path"]
    # 写死逻辑：只要有play_url就强制下载
    if play_url:
        download_result = await call_mcp_tool_via_protocol("video_download", "download_video_by_url", {"play_url": play_url})
        results_dict["auto_video_download_result"] = download_result
        file_path = download_result.get("file_path")
    # 如果有file_path但没有分析结果，自动分析
    if file_path and not any(
        k for k in results_dict if k.startswith("contentunderstanding_analyze_local_video") or k.startswith("auto_video_analysis_result")
    ):
        analysis_result = await call_mcp_tool_via_protocol("contentunderstanding", "analyze_local_video", {"file_path": file_path})
        results_dict["auto_video_analysis_result"] = analysis_result
    return results_dict

# --- API Endpoints ---
@app.post("/gpt_agent", summary="让GPT自动决定调用Twitter或TikTok MCP工具并处理结果")
async def gpt_agent_endpoint(payload: Dict[str, Any]) -> Any:
    original_task = payload.get("task")
    if not original_task:
        raise HTTPException(status_code=400, detail="Missing 'task' in payload.")

    agent_log = {
        "original_task": original_task,
        "stages": [],
        "redis_log": []
    }

    # --- Combined Tool Capabilities ---
    TWITTER_TOOLS_CAPABILITIES = """**Twitter (`twitter`) - Available Tools & Usage:**

*   `get_user_info(screenname: str, rest_id: str)`: Fetches detailed user information.
    *   Args: `{"screenname": "USER_SCREENNAME", "rest_id": "USER_REST_ID"}`. (Note: `rest_id` is a numerical ID, e.g., "44196397" for elonmusk. If unknown, can be an empty string, but providing it helps accuracy if screenname is ambiguous).
    *   Returns: User object containing screenname, rest_id, description, follower/following counts, etc. Useful for getting user IDs.

*   `get_user_timeline(screenname: str)`: Fetches a user's most recent tweets (their timeline).
    *   Args: {"screenname": "USER_SCREENNAME"}.
    *   Returns: A list of tweets. Each tweet may contain text, tweet ID, author info, etc.

*   `get_user_following(screenname: str)`: Fetches the list of users a given user is following.
    *   Args: {"screenname": "USER_SCREENNAME"}.
    *   Returns: A list of user objects.

*   `get_user_followers(screenname: str, blue_verified: int = 0)`: Fetches the list of followers for a user.
    *   Args: {"screenname": "USER_SCREENNAME", "blue_verified": 0_OR_1}. (0 for all, 1 for blue verified only. Defaults to 0).
    *   Returns: A list of user objects.

*   `get_tweet_info(tweet_id: str)`: Fetches detailed information for a specific tweet.
    *   Args: {"tweet_id": "TWEET_ID_STRING"}.
    *   Returns: Tweet object containing text, author details, engagement counts, potentially linked media, etc.

*   `get_affiliates(screenname: str)`: Fetches affiliates for a given user (e.g., "x").
    *   Args: {"screenname": "USER_SCREENNAME"}.
    *   Returns: Information about affiliated accounts or entities.

*   `get_user_media(screenname: str)`: Fetches media (images, videos) posted by a user.
    *   Args: {"screenname": "USER_SCREENNAME"}.
    *   Returns: A list of media objects or tweets containing media.

*   `get_retweets(tweet_id: str)`: Fetches users who retweeted a specific tweet.
    *   Args: {"tweet_id": "TWEET_ID_STRING"}.
    *   Returns: A list of user objects who retweeted.

*   `get_trends(country: str)`: Fetches trending topics for a specified country.
    *   Args: {"country": "COUNTRY_NAME"}.
    *   Returns: A list of trending topics.

*   `search_tweets(query: str, search_type: str = "Top")`: Searches tweets based on a query.
    *   Args: {"query": "SEARCH_QUERY", "search_type": "Top_OR_Latest"}. (Defaults to "Top").
    *   Returns: A list of tweets matching the query. Each tweet object includes text, author info (screenname, user_id), tweet_id, etc. This is key for finding tweets by keyword.

*   `get_tweet_thread(tweet_id: str)`: Fetches a conversation thread starting from a specific tweet.
    *   Args: {"tweet_id": "TWEET_ID_STRING"}.
    *   Returns: A list of tweets forming the thread/conversation.

*   `get_latest_replies(tweet_id: str)`: Fetches the latest replies to a specific tweet.
    *   Args: {"tweet_id": "TWEET_ID_STRING"}.
    *   Returns: A list of reply tweets. Useful for getting comments on a specific tweet. The result of this often contains the user who made the reply (commenter) and the reply content.

*   `get_list_timeline(list_id: str)`: Fetches the timeline for a specific Twitter list.
    *   Args: {"list_id": "LIST_ID_STRING"}.
    *   Returns: A list of tweets from that list.

*   `search_communities_latest(query: str)`: Searches community posts (latest) by query.
    *   Args: {"query": "SEARCH_QUERY"}.
    *   Returns: A list of community posts.

*   `search_communities_top(query: str)`: Searches community posts (top) by query.
    *   Args: {"query": "SEARCH_QUERY"}.
    *   Returns: A list of community posts.

*   `search_communities(query: str)`: Searches communities by query.
    *   Args: {"query": "SEARCH_QUERY"}.
    *   Returns: A list of communities.

*   `get_community_timeline(community_id: str)`: Fetches the timeline for a community.
    *   Args: {"community_id": "COMMUNITY_ID_STRING"}.
    *   Returns: A list of posts from that community.

*   `get_list_followers(list_id: str)`: Fetches followers of a specific Twitter list.
    *   Args: {"list_id": "LIST_ID_STRING"}.
    *   Returns: A list of user objects.

*   `get_list_members(list_id: str)`: Fetches members of a specific Twitter list.
    *   Args: {"list_id": "LIST_ID_STRING"}.
    *   Returns: A list of user objects.

**Tool Chaining Example for Complex Queries:**
If a user asks "For tweets about 'X', show the tweet, its author, and recent comments":
1.  First call: `search_tweets(query="X")` to get a list of relevant tweets.
2.  For each tweet found, you get a `tweet_id` and author information (like `screenname`).
3.  To get more details about the author: `get_user_info(screenname=author_screenname, rest_id=author_rest_id_if_available)`.
4.  To get comments for a specific tweet: `get_latest_replies(tweet_id=the_tweet_id_from_step_2)`.
Remember to extract necessary IDs or screennames from one tool's output to use as input for another.
"""

    TIKTOK_TOOLS_CAPABILITIES = """**TikTok (`tiktok`) - Available Tools & Usage:**

*   `get_user_info(uniqueId: str)`: 获取用户信息 (Fetches user information).
    *   Args: {"uniqueId": "USER_UNIQUE_ID"}.
    *   Returns: User object including user ID, unique ID, nickname, signature, follower/following counts, video count, etc. Provides `secUid` needed for many other user-specific calls.

*   `get_user_info_with_region(uniqueId: str)`: 获取用户信息（包括用户区域） (Fetches user information including region).
    *   Args: {"uniqueId": "USER_UNIQUE_ID"}.
    *   Returns: Similar to `get_user_info` but may include additional region-specific data.

*   `get_user_info_by_id(userId: str)`: 按ID获取用户信息 (Fetches user information by their numerical User ID).
    *   Args: {"userId": "USER_ID_STRING"}.
    *   Returns: User object.

*   `get_user_followers(secUid: str, count: int = 30, minCursor: int = 0)`: 获取用户关注者 (Fetches a list of user's followers).
    *   Args: {"secUid": "USER_SEC_UID", "count": 30, "minCursor": 0}. (`secUid` is obtained from user info calls. `count` is number of items, `minCursor` for pagination).
    *   Returns: List of follower user objects.

*   `get_user_followings(secUid: str, count: int = 30, minCursor: int = 0, maxCursor: int = 0)`: 获取用户关注 (Fetches a list of users a user is following).
    *   Args: {"secUid": "USER_SEC_UID", "count": 30, "minCursor": 0, "maxCursor": 0}.
    *   Returns: List of user objects they follow.

*   `get_user_posts(secUid: str, count: int = 35, cursor: int = 0)`: 获取用户帖子 (Fetches a user's posts/videos).
    *   Args: {"secUid": "USER_SEC_UID", "count": 35, "cursor": 0}.
    *   Returns: List of video/post objects, each containing `videoId`, description, stats, author info, etc.

*   `get_user_popular_posts(secUid: str, count: int = 35, cursor: int = 0)`: 获取用户热门文章 (Fetches a user's popular posts).
    *   Args: {"secUid": "USER_SEC_UID", "count": 35, "cursor": 0}.
    *   Returns: List of popular video/post objects.

*   `get_user_oldest_posts(secUid: str, count: int = 30, cursor: int = 0)`: 获取用户最早的帖子 (Fetches a user's oldest posts).
    *   Args: {"secUid": "USER_SEC_UID", "count": 30, "cursor": 0}.
    *   Returns: List of oldest video/post objects.

*   `get_user_liked_posts(secUid: str, count: int = 30, cursor: int = 0)`: 获取用户最喜欢帖子 (Fetches posts a user has liked).
    *   Args: {"secUid": "USER_SEC_UID", "count": 30, "cursor": 0}.
    *   Returns: List of video/post objects.

*   `get_user_playlist(secUid: str, count: int = 20, cursor: int = 0)`: 获取用户播放列表 (Fetches a user's playlists).
    *   Args: {"secUid": "USER_SEC_UID", "count": 20, "cursor": 0}.
    *   Returns: List of playlists.

*   `get_user_repost(secUid: str, count: int = 30, cursor: int = 0)`: 获取用户重新发布 (Fetches posts a user has reposted).
    *   Args: {"secUid": "USER_SEC_UID", "count": 30, "cursor": 0}.
    *   Returns: List of reposted video/post objects.

*   `search_general(keyword: str, cursor: int = 0, search_id: str = "0")`: 搜索常规（顶部） (General search, top results for a keyword). Note: `search_id` is often a string.
    *   Args: {"keyword": "SEARCH_KEYWORD", "cursor": 0, "search_id": "SEARCH_SESSION_ID_OR_0"}.
    *   Returns: Mixed list of search results (videos, users, etc.).

*   `search_video(keyword: str, cursor: int = 0, search_id: str = "0")`: 搜索视频 (Searches for videos by keyword). Note: `search_id` is often a string.
    *   Args: {"keyword": "SEARCH_KEYWORD", "cursor": 0, "search_id": "SEARCH_SESSION_ID_OR_0"}.
    *   Returns: List of video objects. Each video includes `videoId`, description, author (`uniqueId`, `secUid`).

*   `search_account(keyword: str, cursor: int = 0, search_id: str = "0")`: 搜索账户 (Searches for user accounts by keyword). Note: `search_id` is often a string.
    *   Args: {"keyword": "SEARCH_KEYWORD", "cursor": 0, "search_id": "SEARCH_SESSION_ID_OR_0"}.
    *   Returns: List of user objects.

*   `search_live(keyword: str, cursor: int = 0, search_id: str = "0")`: 搜索Live (Searches for live streams by keyword). Note: `search_id` is often a string. (Endpoint seems to be "api/search/account" in server code, verify if this is correct or a typo for a live-specific endpoint).
    *   Args: {"keyword": "SEARCH_KEYWORD", "cursor": 0, "search_id": "SEARCH_SESSION_ID_OR_0"}.
    *   Returns: List of live stream results or user accounts.

*   `get_post_detail(videoId: str)`: 获取文章详细信息 (Fetches details for a specific post/video).
    *   Args: {"videoId": "VIDEO_ID_STRING"}.
    *   Returns: Detailed video/post object.

*   `get_post_comments(videoId: str, count: int = 50, cursor: int = 0)`: 获取帖子的评论 (Fetches comments for a specific post/video).
    *   Args: {"videoId": "VIDEO_ID_STRING", "count": 50, "cursor": 0}.
    *   Returns: List of comment objects. Each comment includes text, author (`uniqueId`, `secUid`), `commentId`.

*   `get_post_comment_replies(videoId: str, commentId: str, count: int = 6, cursor: int = 0)`: 获取帖子的回复评论 (Fetches replies to a specific comment on a post).
    *   Args: {"videoId": "VIDEO_ID_STRING", "commentId": "COMMENT_ID_STRING", "count": 6, "cursor": 0}.
    *   Returns: List of reply comment objects.

*   `get_post_related(videoId: str, count: int = 16, cursor: int = 0)`: 获取相关文章 (Fetches posts related to a specific post/video).
    *   Args: {"videoId": "VIDEO_ID_STRING", "count": 16, "cursor": 0}.
    *   Returns: List of related video/post objects.

*   `get_post_trending(count: int = 16)`: 获取热点文章 (Fetches trending posts/videos).
    *   Args: {"count": 16}.
    *   Returns: List of trending video/post objects.

*   `download_video(url: str)`: 下载视频 (Downloads a video given its URL).
    *   Args: {"url": "VIDEO_URL_STRING"}.
    *   Returns: Information about the download, potentially a direct link or status.
"""

    LINKEDIN_TOOLS_CAPABILITIES = """**LinkedIn (`linkedin`) - Available Tools & Usage:**

*   `get_profile_by_username(username: str)`: 获取配置文件数据 (Get profile data by username).
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Profile object.

*   `get_profile_by_url(url: str)`: 按url获取配置文件数据 (Get profile data by LinkedIn profile URL).
    *   Args: {"url": "PROFILE_URL"}.
    *   Returns: Profile object.

*   `search_people_by_url(url: str)`: 按url搜索人员 (Search people by LinkedIn search URL).
    *   Args: {"url": "SEARCH_URL"}. (Method: POST)
    *   Returns: List of profile objects.

*   `get_profile_recent_activity_time(username: str)`: 获取配置文件最近的活动时间 (Get profile's recent activity time).
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Activity time information.

*   `get_profile_posts(username: str)`: 获取个人资料的帖子 (Get profile's posts).
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: List of post objects.

*   `get_company_details(username: str)`: 获取公司详细信息 (Get company details by username/company page name).
    *   Args: {"username": "COMPANY_USERNAME"}.
    *   Returns: Company details object.

*   `get_company_by_domain(domain: str)`: 按域获取公司 (Get company by domain).
    *   Args: {"domain": "COMPANY_DOMAIN"}.
    *   Returns: Company details object.

*   `get_post_by_url(url: str)`: 获取帖子 (Get post by URL).
    *   Args: {"url": "POST_URL"}.
    *   Returns: Post object.

*   `get_user_articles(url: str, username: str, page: int = 1)`: 获取用户文章 (Get user articles).
    *   Args: {"url": "PROFILE_OR_ARTICLE_URL", "username": "LINKEDIN_USERNAME", "page": 1}.
    *   Returns: List of article objects.

*   `get_profile_post_and_comments(urn: str)`: 获取个人资料帖子和评论.
    *   Args: {"urn": "POST_URN"}. (URN is a unique LinkedIn identifier for content)
    *   Returns: Post and comments data.

*   `get_profile_posts_comments(urn: str, sort: str = "mostRelevant", page: int = 1)`: 获取个人资料帖子评论.
    *   Args: {"urn": "POST_URN", "sort": "mostRelevant_OR_chronological", "page": 1}.
    *   Returns: List of comment objects.

*   `get_profile_comments(username: str)`: 获取个人资料的评论.
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: List of comment objects made by the user.

*   `get_connection_count(username: str)`: 获取个人资料链接和关注者数量.
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Connection and follower counts.

*   `get_data_connection_count(username: str)`: 获取个人资料数据以及链接和关注者数.
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Profile data with connection/follower counts.

*   `get_given_recommendations(username: str, start: int = 0)`: 获取给定的推荐.
    *   Args: {"username": "LINKEDIN_USERNAME", "start": 0}.
    *   Returns: List of recommendations given by the user.

*   `get_received_recommendations(username: str, start: int = 0)`: 获取收到的推荐.
    *   Args: {"username": "LINKEDIN_USERNAME", "start": 0}.
    *   Returns: List of recommendations received by the user.

*   `get_profile_likes(username: str, start: int = 0)`: 获取个人资料反应 (likes/reactions made by the user).
    *   Args: {"username": "LINKEDIN_USERNAME", "start": 0}.
    *   Returns: List of reactions.

*   `profile_data_connection_count_posts(username: str)`: 获取个人资料数据、连接和关注 (and posts).
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Combined profile data.

*   `all_profile_data(username: str)`: 个人资料数据和推荐.
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Comprehensive profile data including recommendations.

*   `similar_profiles(url: str)`: 获取类似配置文件.
    *   Args: {"url": "PROFILE_URL"}.
    *   Returns: List of similar profile objects.

*   `profiles_position_skills(username: str)`: 获取保护技能的个人资料职位 (Get profile positions and skills).
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: Profile's positions and skills information.

*   `get_company_details_by_id(id: str)`: 按ID获取公司详细信息.
    *   Args: {"id": "COMPANY_ID"}.
    *   Returns: Company details object.

*   `search_companies(keyword: str, locations: list, companySizes: list, hasJobs: bool, industries: list, page: int)`: 搜索公司.
    *   Args: {"keyword": "SEARCH_KEYWORD", "locations": ["USA", "New York"], "companySizes": ["1-10", "11-50"], "hasJobs": true, "industries": ["Technology"], "page": 1}. (Method: POST)
    *   Returns: List of company objects.

*   `company_jobs(companyIds: list, page: int = 1, sort: str = "mostRecent")`: 获取公司职位.
    *   Args: {"companyIds": ["COMPANY_ID_1", "COMPANY_ID_2"], "page": 1, "sort": "mostRecent_OR_..."}. (Method: POST)
    *   Returns: List of job objects.

*   `get_company_employees_count(companyId: str, locations: list = [])`: 获取公司员工人数.
    *   Args: {"companyId": "COMPANY_ID", "locations": ["USA"]}. (Method: POST)
    *   Returns: Employee count.

*   `get_company_jobs_count(companyId: str)`: 获取公司职位计数.
    *   Args: {"companyId": "COMPANY_ID"}.
    *   Returns: Job count.

*   `get_company_posts(username: str, start: int = 0)`: 获取公司的帖子 (by company page name/username).
    *   Args: {"username": "COMPANY_USERNAME", "start": 0}.
    *   Returns: List of company post objects.

*   `get_company_post_comments(urn: str, sort: str = "mostRelevant", page: int = 1)`: 获取公司的帖子评论.
    *   Args: {"urn": "POST_URN", "sort": "mostRelevant_OR_chronological", "page": 1}.
    *   Returns: List of comment objects.

*   `linkedin_to_email(url: str)`: 查找电子邮件地址 (for a profile URL).
    *   Args: {"url": "PROFILE_URL"}.
    *   Returns: Email information if found.

*   `get_job_details(id: str)`: 获取作业详细信息 (by job ID).
    *   Args: {"id": "JOB_ID"}.
    *   Returns: Job details object.

*   `profiles_posted_jobs(username: str)`: 获取个人资料的已发布的职位.
    *   Args: {"username": "LINKEDIN_USERNAME"}.
    *   Returns: List of jobs posted by the user.

*   `search_posts(keyword: str, sortBy: str = "date_posted", datePosted: str = "", page: int = 1, contentType: str = "", fromMember: list = None, fromCompany: list = None, mentionsMember: list = None, mentionsOrganization: list = None, authorIndustry: list = None, authorCompany: list = None, authorTitle: str = "")`: 搜索帖子.
    *   Args: Example: {"keyword": "AI", "sortBy": "date_posted", "page": 1}. (Method: POST, many optional filters)
    *   Returns: List of post objects.

*   `get_post_reposts(urn: str, page: int = 1, paginationToken: str = "")`: 获取帖子的转发.
    *   Args: {"urn": "POST_URN", "page": 1, "paginationToken": "TOKEN_IF_ANY"}. (Method: POST)
    *   Returns: List of repost objects or users who reposted.

*   `get_post_reactions(url: str, page: int = 1)`: 获取帖子的回应.
    *   Args: {"url": "POST_URL", "page": 1}. (Method: POST)
    *   Returns: List of reaction objects or users who reacted.

*   `get_article(url: str)`: 获取文章.
    *   Args: {"url": "ARTICLE_URL"}.
    *   Returns: Article object.

*   `get_article_comments(url: str, page: int = 1, sort: str = "REVERSE_CHRONOLOGICAL")`: 获取文章评论.
    *   Args: {"url": "ARTICLE_URL", "page": 1, "sort": "REVERSE_CHRONOLOGICAL_OR_..."}.
    *   Returns: List of comment objects.

*   `get_article_reactions(url: str, page: int = 1)`: 获取文章回应.
    *   Args: {"url": "ARTICLE_URL", "page": 1}.
    *   Returns: List of reaction objects.
"""

    CONTENT_UNDERSTANDING_TOOLS_CAPABILITIES = """**Content Understanding (`contentunderstanding`) - Available Tools & Usage:**

*   `analyze_local_video(file_path: str)`: Analyzes a video file stored locally (previously downloaded by the system) and returns a description and tags.
    *   Args: `{\"file_path\": \"ABSOLUTE_LOCAL_PATH_TO_VIDEO\"}`. (This path is determined by the system after a video download, not directly by the user or LLM).
    *   Returns: An object containing `file_name`, `description`, `tags`, `duration_seconds`, `resolution`. Useful for understanding video content after a download step.
"""

    VIDEO_DOWNLOAD_TOOLS_CAPABILITIES = """**Video Download (`video_download`) - Available Tools & Usage:**

*   `download_video_by_url(play_url: str)`: Downloads a video from a direct video URL to the local server and returns the local file path.
    *   Args: `{\"play_url\": \"VIDEO_DIRECT_URL\"}`
    *   Returns: `{\"file_path\": \"/tmp/mcp_video_downloads/xxx.mp4\"}`
"""

    ALL_TOOLS_CAPABILITIES = TWITTER_TOOLS_CAPABILITIES + "\n\n" + TIKTOK_TOOLS_CAPABILITIES + "\n\n" + LINKEDIN_TOOLS_CAPABILITIES + "\n\n" + CONTENT_UNDERSTANDING_TOOLS_CAPABILITIES + "\n\n" + VIDEO_DOWNLOAD_TOOLS_CAPABILITIES

    # --- STAGE 1: Initial Parse & Call ---
    stage1_log = {"name": "Stage 1: Initial Parse & Call", "status": "pending"}
    agent_log["stages"].append(stage1_log)

    initial_parse_prompt_messages = [
        {"role": "system", "content": f"""你是一个多平台API的初步解析代理。用户的任务可能涉及Twitter、TikTok、LinkedIn，或下载TikTok视频后进行内容理解，或者以上都不涉及。
        你的目标是：
        1. 理解用户的最终意图，并判断请求主要针对哪个平台（twitter, tiktok, linkedin）或是否为通用知识问题。注意：`contentunderstanding`平台不应被直接选为主要平台，它是一个辅助平台。
        2. 你可以灵活调用所有可用工具（包括 search_account、get_user_posts、get_video_download_url、download_video_by_url、analyze_local_video 等），自动多步推理，直到完成用户需求。
        3. 每一步只返回下一个工具需要的关键信息（如用户名、视频ID、视频URL、play直链、本地路径等），不要返回冗余内容或超长文本。
        4. 如果需要多步推理，请自动串联多步工具调用，直到最终完成用户需求。
        5. 如果你拿到 TikTok 用户名（如 unique_id/username）和视频ID（如 video_id），必须自动拼接 TikTok 视频页 URL，格式为：https://www.tiktok.com/@{{username}}/video/{{video_id}}，然后用该 URL 作为参数调用 get_video_download_url 工具。
        6. 生成一个初步的后续处理指令（`process_instructions`）。
        7. **重要**: 如果用户请求不需要调用任何平台工具，则将 `calls` 列表设置为空 (`[]`)，并在 `direct_answer_if_no_tools` 字段中直接提供答案。

        可用工具（注意每个工具描述前的平台标识）：
        {ALL_TOOLS_CAPABILITIES}

        输出必须是严格的JSON格式。`platform`字段必须小写。
        案例1 (多步推理):
        用户只给了 TikTok 用户名，模型应自动：
        1. 用 search_account 查找用户
        2. 用 get_user_posts 查找视频ID
        3. 拼接 TikTok 视频页 URL
        4. 用 get_video_download_url 拿到 play 字段
        5. 用 download_video_by_url 下载
        6. 用 analyze_local_video 分析
        每一步只返回下一个工具需要的关键信息。
        """},
        {"role": "user", "content": f"用户原始任务：{original_task}"}
    ]
    stage1_log["initial_parse_prompt"] = initial_parse_prompt_messages
    initial_calls, initial_process_instructions, initial_results = [], "", {}
    direct_answer_from_stage1 = None

    try:
        print("\n[DEBUG] Stage 1: messages to GPT (initial_parse_prompt_messages):\n", json.dumps(initial_parse_prompt_messages, ensure_ascii=False)[:2000], "...\n[total chars]", len(json.dumps(initial_parse_prompt_messages, ensure_ascii=False)))
        gpt_response = openai_client.chat.completions.create(
            model="gpt-4o-mini", messages=initial_parse_prompt_messages, max_tokens=1500, temperature=0.1, response_format={"type": "json_object"}
        )
        parsed_content = gpt_response.choices[0].message.content
        stage1_log["initial_parse_gpt_response"] = parsed_content
        initial_plan = json.loads(parsed_content)
        
        raw_calls_value = initial_plan.get("calls")
        if isinstance(raw_calls_value, list):
            initial_calls = raw_calls_value
        elif raw_calls_value is None:
            initial_calls = []
        else:
            warning_msg = f"GPT Stage 1 returned 'calls' not as a list or null (type: {type(raw_calls_value)}, value: {raw_calls_value}). Defaulting to empty list."
            print(f"Warning: {warning_msg}")
            stage1_log["warning_calls_format"] = warning_msg
            initial_calls = []
        
        direct_answer_from_stage1 = initial_plan.get("direct_answer_if_no_tools")
        initial_process_instructions = initial_plan.get("process_instructions", f"根据初步结果，决定下一步骤以完成用户任务: {original_task}")
        
        stage1_log["parsed_initial_calls"] = initial_calls
        stage1_log["parsed_initial_process_instructions"] = initial_process_instructions
        stage1_log["parsed_direct_answer"] = direct_answer_from_stage1

        if direct_answer_from_stage1 and isinstance(direct_answer_from_stage1, str) and direct_answer_from_stage1.strip() and not initial_calls:
            agent_log["final_gpt_processed_result"] = direct_answer_from_stage1
            stage1_log["status"] = "completed_direct_answer"
        elif initial_calls:
            for i, call_info in enumerate(initial_calls):
                platform = call_info.get("platform", "").lower()
                tool_name = call_info.get("tool_name")
                params = call_info.get("params", {})

                if not platform or not tool_name:
                    initial_results[f"call_{i}_skipped"] = f"Invalid/Missing platform ('{platform}') or tool_name ('{tool_name}')."
                    continue
                try:
                    # 新逻辑：如果是 tiktok.download_video，先调用 TikTok MCP 拿到 file_path，再自动调用 contentunderstanding.analyze_local_video
                    if platform == "tiktok" and tool_name == "download_video":
                        download_result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                        file_path = download_result.get("file_path")
                        initial_results[f"tiktok_download_video_result_{i}"] = download_result
                        if file_path:
                            analysis_result = await call_mcp_tool_via_protocol(
                                platform="contentunderstanding",
                                tool_name="analyze_local_video",
                                params={"file_path": file_path}
                            )
                            initial_results[f"contentunderstanding_analyze_local_video_from_{file_path}"] = analysis_result
                        else:
                            initial_results[f"tiktok_download_video_error_{i}"] = "No file_path returned"
                    else:
                        result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                        initial_results[f"{platform}_{tool_name}_{i}"] = result
                except Exception as e:
                    initial_results[f"{platform}_{tool_name}_{i}_error"] = str(e)
                    traceback.print_exc()

            # 自动补全链路
            initial_results = await auto_chain_tiktok_video_analysis(initial_results)
            stage1_log["initial_call_results"] = initial_results
            if any(k.startswith("tiktok_download_video_result_") for k in initial_results):
                stage1_log["status"] = "completed_pending_download_analysis"
            elif initial_results:
                stage1_log["status"] = "completed_with_calls"
            else:
                stage1_log["status"] = "completed_no_effective_calls"
        else:
            stage1_log["status"] = "completed_no_action_plan"

    except Exception as e:
        stage1_log["status"] = "failed"
        stage1_log["error"] = f"Stage 1 failed: {type(e).__name__} - {str(e)}"
        agent_log["final_gpt_processed_result"] = stage1_log["error"]
        traceback.print_exc()

    # --- STAGE 2: Derivative Planning & Call ---
    stage2_log = {"name": "Stage 2: Derivative Planning", "status": "pending"}
    agent_log["stages"].append(stage2_log)
    derivative_calls, final_process_instructions, derivative_results = [], initial_process_instructions, {}

    if stage1_log.get("status") not in ["completed_direct_answer", "failed"]:
        parsed_initial_results_for_prompt = {}
        for key, value in initial_results.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict) and 'text' in value[0] and isinstance(value[0]['text'], str):
                try: parsed_initial_results_for_prompt[key] = json.loads(value[0]['text'])
                except: parsed_initial_results_for_prompt[key] = value
            else: parsed_initial_results_for_prompt[key] = value

        plan_derivative_prompt_messages = [
            {"role": "system", "content": f"""你是一个多平台任务深化专家。信息：
            1. 用户任务：`{original_task}`
            2. 初步指示：`{initial_process_instructions}`
            3. 初步结果：`{json.dumps(parsed_initial_results_for_prompt, ensure_ascii=False, default=str)}`
            
            任务：
            A. 你可以灵活调用所有可用工具（包括 search_account、get_user_posts、get_video_download_url、download_video_by_url、analyze_local_video 等），自动多步推理，直到完成用户需求。
            B. 每一步只返回下一个工具需要的关键信息（如用户名、视频ID、视频URL、play直链、本地路径等），不要返回冗余内容或超长文本。
            C. 如果你拿到 TikTok 用户名（如 unique_id/username）和视频ID（如 video_id），必须自动拼接 TikTok 视频页 URL，格式为：https://www.tiktok.com/@{{username}}/video/{{video_id}}，然后用该 URL 作为参数调用 get_video_download_url 工具。
            D. 如果需要其他非分析类的API调用（例如，根据第一步的结果获取更多Twitter信息），将它们也加入到 derivative_calls 列表中。
            E. 生成final_process_instructions指导最终整合。此指令应明确提及如果视频被分析了，则应在其最终摘要中包含视频的描述和标签。
            
            **多步推理链式范例：**
            1. 用户只给了 TikTok 用户名，自动：
               - search_account 查找用户
               - get_user_posts 查找视频ID
               - 拼接 TikTok 视频页 URL
               - get_video_download_url 拿到 play 字段
               - download_video_by_url 下载
               - analyze_local_video 分析
            2. 每一步只返回下一个工具需要的关键信息。
            
            可用工具（注意平台）：
            {ALL_TOOLS_CAPABILITIES}
            
            输出JSON示例：
            {{
              "derivative_calls": [
                {{
                  "platform": "video_download",
                  "tool_name": "download_video_by_url",
                  "params": {{"play_url": "PLAY_URL_FROM_PREVIOUS_RESULT"}}
                }},
                {{
                  "platform": "contentunderstanding",
                  "tool_name": "analyze_local_video",
                  "params": {{"file_path": "LOCAL_PATH_FROM_PREVIOUS_RESULT"}}
                }}
              ],
              "final_process_instructions": "已下载并分析TikTok视频。总结时请包含其内容描述和标签。"
            }}
            如果初步结果不足或失败，或者没有待分析的视频文件路径，final_process_instructions应指导如何向用户解释，并且 derivative_calls 中不应包含 analyze_local_video（除非有其他平台的调用需求）。
            """},
            {"role": "user", "content": "请规划下一步。"}
        ]
        stage2_log["plan_derivative_prompt"] = plan_derivative_prompt_messages

        try:
            print("\n[DEBUG] Stage 2: messages to GPT (plan_derivative_prompt_messages):\n", json.dumps(plan_derivative_prompt_messages, ensure_ascii=False)[:2000], "...\n[total chars]", len(json.dumps(plan_derivative_prompt_messages, ensure_ascii=False)))
            gpt_response = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=plan_derivative_prompt_messages, max_tokens=1500, temperature=0.1, response_format={"type": "json_object"}
            )
            parsed_content = gpt_response.choices[0].message.content
            stage2_log["plan_derivative_gpt_response"] = parsed_content
            derivative_plan = json.loads(parsed_content)

            derivative_calls = derivative_plan.get("derivative_calls", [])
            final_process_instructions = derivative_plan.get("final_process_instructions", initial_process_instructions)
            stage2_log["parsed_derivative_calls"] = derivative_calls
            stage2_log["parsed_final_process_instructions"] = final_process_instructions

            if derivative_calls:
                for i, call_info in enumerate(derivative_calls):
                    platform = call_info.get("platform", "").lower()
                    tool_name = call_info.get("tool_name")
                    params = call_info.get("params", {})

                    # 新逻辑：如果是 tiktok.download_video，先调用 TikTok MCP 拿到 file_path，再自动调用 contentunderstanding.analyze_local_video
                    if platform == "tiktok" and tool_name == "download_video":
                        download_result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                        file_path = download_result.get("file_path")
                        derivative_results[f"tiktok_download_video_result_deriv_{i}"] = download_result
                        if file_path:
                            analysis_result = await call_mcp_tool_via_protocol(
                                platform="contentunderstanding",
                                tool_name="analyze_local_video",
                                params={"file_path": file_path}
                            )
                            derivative_results[f"contentunderstanding_analyze_local_video_from_{file_path}_deriv"] = analysis_result
                        else:
                            derivative_results[f"tiktok_download_video_error_deriv_{i}"] = "No file_path returned"
                    else:
                        try:
                            result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                            derivative_results[f"{platform}_{tool_name}_deriv_{i}"] = result
                        except Exception as e:
                            derivative_results[f"{platform}_{tool_name}_deriv_{i}_error"] = str(e)
                # 自动补全链路
                derivative_results = await auto_chain_tiktok_video_analysis(derivative_results)
                stage2_log["derivative_call_results"] = derivative_results
                stage2_log["status"] = "completed"
        except Exception as e:
            stage2_log["status"] = "failed"
            stage2_log["error"] = f"Stage 2 failed: {type(e).__name__} - {str(e)}"
            traceback.print_exc()

    # --- STAGE 3: Final Processing & Response ---
    stage3_log = {"name": "Stage 3: Final Processing", "status": "pending"}
    agent_log["stages"].append(stage3_log)
    all_collated_results = {**initial_results, **derivative_results}
    
    if stage1_log.get("status") != "completed_direct_answer":
        agent_log["final_gpt_processed_result"] = ""

    if stage1_log.get("status") not in ["completed_direct_answer", "failed"]:
        parsed_all_collated_results_for_prompt = {}
        for key, value in all_collated_results.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict) and 'text' in value[0] and isinstance(value[0]['text'], str):
                try: parsed_all_collated_results_for_prompt[key] = json.loads(value[0]['text'])
                except: parsed_all_collated_results_for_prompt[key] = value
            else: parsed_all_collated_results_for_prompt[key] = value

        final_processing_prompt_messages = [
            {"role": "system", "content": f"""你是多平台数据处理专家。任务：根据指令，整合API结果(可能来自Twitter、TikTok或LinkedIn)，生成中文回复回答用户原始请求。
            原始请求：`{original_task}`
            处理指令：`{final_process_instructions}`
            API结果：`{json.dumps(parsed_all_collated_results_for_prompt, ensure_ascii=False, default=str)}`
            
            严格按指令总结。若信息不足，请指出。输出为最终用户答案。"""},
            {"role": "user", "content": "请生成最终答复。"}
        ]
        stage3_log["final_processing_prompt"] = final_processing_prompt_messages

        try:
            print("\n[DEBUG] Stage 3: messages to GPT (final_processing_prompt_messages):\n", json.dumps(final_processing_prompt_messages, ensure_ascii=False)[:2000], "...\n[total chars]", len(json.dumps(final_processing_prompt_messages, ensure_ascii=False)))
            gpt_response = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=final_processing_prompt_messages, max_tokens=2000, temperature=0.7
            )
            final_gpt_processed_result_content = gpt_response.choices[0].message.content
            stage3_log["final_gpt_response"] = final_gpt_processed_result_content
            agent_log["final_gpt_processed_result"] = final_gpt_processed_result_content
            stage3_log["status"] = "completed"
        except Exception as e:
            stage3_log["status"] = "failed"
            stage3_log["error"] = f"Stage 3 failed: {type(e).__name__} - {str(e)}"
            agent_log["final_gpt_processed_result"] = stage3_log["error"]
            traceback.print_exc()

    # --- Write to Redis (final step before returning agent_log) ---
    final_answer_for_redis = agent_log.get("final_gpt_processed_result")

    if "redis_log" not in agent_log:
        agent_log["redis_log"] = []

    if redis_client and final_answer_for_redis and isinstance(final_answer_for_redis, str) and final_answer_for_redis.strip():
        try:
            task_hash = hashlib.md5(original_task.encode('utf-8')).hexdigest()
            session_key = f"multi_agent_history:{task_hash}"
            
            user_message_entry = {"role": "user", "content": original_task}
            assistant_message_entry = {"role": "assistant", "content": final_answer_for_redis}
            
            await redis_client.rpush(session_key, json.dumps(user_message_entry), json.dumps(assistant_message_entry))
            await redis_client.expire(session_key, 3600 * 24) 
            
            redis_msg = f"Conversation history (key: {session_key}) written to Redis."
            print(redis_msg); agent_log["redis_log"].append(redis_msg)
        except Exception as e_redis:
            redis_err_msg = f"Error writing to Redis: {type(e_redis).__name__} - {str(e_redis)}"
            print(redis_err_msg); agent_log["redis_log"].append(redis_err_msg)
            traceback.print_exc()
    elif not redis_client: 
        agent_log["redis_log"].append("Redis client not available. Skipping history write.")
    elif not final_answer_for_redis or not isinstance(final_answer_for_redis, str) or not final_answer_for_redis.strip():
         agent_log["redis_log"].append("No final answer processed or answer is empty/invalid. Skipping Redis write.")

    # 只返回最终结果字段
    return agent_log.get("final_gpt_processed_result", "")

@app.get("/chat_history", summary="查询历史对话内容")
async def get_chat_history(
    task: Optional[str] = Query(None, description="原始任务内容，可选"),
    task_hash: Optional[str] = Query(None, description="任务内容的md5哈希，可选"),
    limit: int = Query(20, description="返回的历史条数，默认20")
):
    """
    查询历史对话内容（从Redis）。
    支持通过原始task或task_hash查询。re
    """
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis不可用，无法查询历史。")

    # 计算key
    if task_hash:
        session_key = f"multi_agent_history:{task_hash}"
    elif task:
        import hashlib
        task_hash = hashlib.md5(task.encode('utf-8')).hexdigest()
        session_key = f"multi_agent_history:{task_hash}"
    else:
        raise HTTPException(status_code=400, detail="请提供task或task_hash参数。")

    # 查询历史
    try:
        history = await redis_client.lrange(session_key, -limit, -1)
        # 解析为对象
        history = [json.loads(item) for item in history]
        # 只返回每条历史的 content 字段（即最终回复内容）
        final_results = [item.get("content", "") for item in history if item.get("role") == "assistant"]
        return {"session_key": session_key, "history": final_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询历史失败: {str(e)}")

@app.get("/chat_history_index", summary="获取所有历史会话索引")
async def chat_history_index():
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis不可用")
    try:
        # 获取所有历史会话的 key
        keys = await redis_client.keys("multi_agent_history:*")
        sessions = []
        for key in keys:
            # 取第一条消息，解析出 task
            items = await redis_client.lrange(key, 0, 0)
            if items:
                try:
                    msg = json.loads(items[0])
                    if msg.get("role") == "user":
                        sessions.append({
                            "session_key": key,
                            "task": msg.get("content", "")
                        })
                except Exception:
                    continue
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取历史索引失败: {str(e)}")

@app.delete("/delete_session", summary="删除指定历史会话")
async def delete_session(session_key: str = Query(..., description="Redis中的会话key")):
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis不可用，无法删除历史。")
    try:
        await redis_client.delete(session_key)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除历史失败: {str(e)}")

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    print("Starting MCP Client API server (Twitter, TikTok & LinkedIn Agent with Redis) on http://localhost:8080")
    print("Access OpenAPI docs at http://localhost:8080/docs")
    print("\nExample POST request to gpt_agent for multi-platform tasks:")
    print("""curl -X POST -H "Content-Type: application/json" -d '{"task": "获取Twitter用户elonmusk的粉丝数，搜索TikTok上关于猫的视频，并查找LinkedIn用户billgates的资料"}' http://localhost:8080/gpt_agent""" )
    uvicorn.run(app, host="0.0.0.0", port=8080) 