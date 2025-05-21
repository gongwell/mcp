import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Optional
from contextlib import AsyncExitStack, asynccontextmanager
import os
import traceback
import json
import hashlib

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
    
    yield
    
    if redis_client:
        print("Closing Redis connection...")
        await redis_client.close()
        print("Redis connection closed.")

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MCP Client API - Twitter & TikTok Agent",
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

# --- API Endpoints ---
@app.post("/gpt_agent", summary="让GPT自动决定调用Twitter或TikTok MCP工具并处理结果")
async def gpt_agent_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
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

    ALL_TOOLS_CAPABILITIES = TWITTER_TOOLS_CAPABILITIES + "\n\n" + TIKTOK_TOOLS_CAPABILITIES

    # --- STAGE 1: Initial Parse & Call ---
    stage1_log = {"name": "Stage 1: Initial Parse & Call", "status": "pending"}
    agent_log["stages"].append(stage1_log)

    initial_parse_prompt_messages = [
        {"role": "system", "content": f"""你是一个多平台API的初步解析代理。用户的任务可能涉及Twitter或TikTok，或者两者都不涉及。
        你的目标是：
        1. 理解用户的最终意图，并判断请求主要针对哪个平台（twitter, tiktok）或是否为通用知识问题。
        2. 如果需要调用工具，为相应的平台生成第一批API调用（`calls`列表）。每个调用必须包含`platform` ('twitter' or 'tiktok')、`tool_name`和`params`。
        3. 生成一个初步的后续处理指令（`process_instructions`）。
        4. **重要**: 如果用户请求不需要调用任何平台工具，则将 `calls` 列表设置为空 (`[]`)，并在 `direct_answer_if_no_tools` 字段中直接提供答案。

        可用工具（注意每个工具描述前的平台标识，如 **Twitter (`twitter`)** 或 **TikTok (`tiktok`)**）：
        {ALL_TOOLS_CAPABILITIES}

        输出必须是严格的JSON格式。`platform`字段必须小写。
        案例1 (Twitter工具): {{"calls": [{{"platform": "twitter", "tool_name": "get_user_info", "params": {{"screenname": "elonmusk", "rest_id": ""}}}}], "process_instructions": "获取用户信息后...", "direct_answer_if_no_tools": null}}
        案例2 (TikTok工具): {{"calls": [{{"platform": "tiktok", "tool_name": "get_user_info", "params": {{"uniqueId": "taylorswift"}}}}], "process_instructions": "获取用户信息后...", "direct_answer_if_no_tools": null}}
        案例3 (无需工具): {{"calls": [], "process_instructions": "用户问题已直接回答。", "direct_answer_if_no_tools": "太阳从东方升起。"}}
        """},
        {"role": "user", "content": f"用户原始任务：{original_task}"}
    ]
    stage1_log["initial_parse_prompt"] = initial_parse_prompt_messages
    initial_calls, initial_process_instructions, initial_results = [], "", {}
    direct_answer_from_stage1 = None

    try:
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
                    result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                    initial_results[f"{platform}_{tool_name}_{i}"] = result
                except Exception as e:
                    initial_results[f"{platform}_{tool_name}_{i}_error"] = str(e)
            stage1_log["initial_call_results"] = initial_results
            stage1_log["status"] = "completed_with_calls"
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
            A. 评估是否需进一步API调用 (Twitter或TikTok) 以满足任务。
            B. 如需，生成`derivative_calls`列表 (JSON格式)，每个调用必须包含`platform` ('twitter' or 'tiktok')。
            C. 生成`final_process_instructions`指导最终整合。
            
            可用工具（注意平台）：
            {ALL_TOOLS_CAPABILITIES}
            
            输出JSON：{{"derivative_calls": [...], "final_process_instructions": "..."}}
            如果初步结果不足或失败，`final_process_instructions`应指导如何向用户解释，`derivative_calls`应为空。
            """},
            {"role": "user", "content": "请规划下一步。"}
        ]
        stage2_log["plan_derivative_prompt"] = plan_derivative_prompt_messages

        try:
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

            if derivative_calls and isinstance(derivative_calls, list):
                for i, call_info in enumerate(derivative_calls):
                    platform = call_info.get("platform", "").lower()
                    tool_name = call_info.get("tool_name")
                    params = call_info.get("params", {})
                    if not platform or not tool_name:
                        derivative_results[f"deriv_call_{i}_skipped"] = f"Invalid/Missing platform ('{platform}') or tool_name ('{tool_name}') for derivative call."
                        continue
                    try:
                        result = await call_mcp_tool_via_protocol(platform, tool_name, params)
                        derivative_results[f"{platform}_{tool_name}_deriv_{i}"] = result
                    except Exception as e:
                        derivative_results[f"{platform}_{tool_name}_deriv_{i}_error"] = str(e)
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
            {"role": "system", "content": f"""你是多平台数据处理专家。任务：根据指令，整合API结果(可能来自Twitter和TikTok)，生成中文回复回答用户原始请求。
            原始请求：`{original_task}`
            处理指令：`{final_process_instructions}`
            API结果：`{json.dumps(parsed_all_collated_results_for_prompt, ensure_ascii=False, default=str)}`
            
            严格按指令总结。若信息不足，请指出。输出为最终用户答案。"""},
            {"role": "user", "content": "请生成最终答复。"}
        ]
        stage3_log["final_processing_prompt"] = final_processing_prompt_messages

        try:
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

    return agent_log

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    print("Starting MCP Client API server (Twitter & TikTok Agent with Redis) on http://localhost:8080")
    print("Access OpenAPI docs at http://localhost:8080/docs")
    print("\nExample POST request to gpt_agent for multi-platform tasks:")
    print("""curl -X POST -H "Content-Type: application/json" -d '{"task": "获取Twitter用户elonmusk的粉丝数，并搜索TikTok上关于猫的视频"}' http://localhost:8080/gpt_agent""" )
    uvicorn.run(app, host="0.0.0.0", port=8080) 