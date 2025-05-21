import httpx
from typing import Any, Dict
import asyncio

# Attempt to import FastMCP from the expected location
try:
    from mcp.server.fastmcp.server import FastMCP
except ImportError:
    # Fallback or raise an error if MCP framework structure is different
    # For now, we'll define a dummy FastMCP if not found, 
    # but the user needs to ensure their MCP environment is set up.
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
            # In a real server, you might have an asyncio loop here.
            # For the dummy server, we'll just simulate running the test main.
            # if __name__ == "twitter_mcp_server": # A bit of a hack to ensure it runs in test
            async def run_main_test():
                await main()
            print("Dummy FastMCP is 'running' the test main function.")
            asyncio.run(run_main_test())


# Instantiate the server object with one of the expected names (e.g., mcp, server, app)
mcp = FastMCP(host="0.0.0.0", port=8000)


TWITTER_API_KEY = ""
TWITTER_API_HOST = "twitter-api45.p.rapidapi.com"
TWITTER_API_BASE_URL = "https://twitter-api45.p.rapidapi.com"
USER_AGENT = "MCPTwitterClient/1.0"

async def make_twitter_request(endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any] | str:
    """Sends a request to the Twitter API and handles errors."""
    headers = {
        "x-rapidapi-key": TWITTER_API_KEY,
        "x-rapidapi-host": TWITTER_API_HOST,
        "User-Agent": USER_AGENT
    }
    url = f"{TWITTER_API_BASE_URL}/{endpoint}"
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
async def get_user_info(screenname: str, rest_id: str) -> Dict[str, Any] | str:
    """
    Fetches user information from Twitter.

    Args:
        screenname: The Twitter screen name (e.g., elonmusk).
        rest_id: The rest_id of the user (e.g., 44196397).
    """
    params = {"screenname": screenname, "rest_id": rest_id}
    return await make_twitter_request("screenname.php", params)

@mcp.tool()
async def get_user_timeline(screenname: str) -> Dict[str, Any] | str:
    """
    Fetches the timeline for a given user.

    Args:
        screenname: The Twitter screen name.
    """
    params = {"screenname": screenname}
    return await make_twitter_request("timeline.php", params)

@mcp.tool()
async def get_user_following(screenname: str) -> Dict[str, Any] | str:
    """
    Fetches the list of users a given user is following.

    Args:
        screenname: The Twitter screen name.
    """
    params = {"screenname": screenname}
    return await make_twitter_request("following.php", params)

@mcp.tool()
async def get_user_followers(screenname: str, blue_verified: int = 0) -> Dict[str, Any] | str:
    """
    Fetches the list of followers for a given user.

    Args:
        screenname: The Twitter screen name.
        blue_verified: Filter by blue verified status (0 or 1). Defaults to 0.
    """
    params = {"screenname": screenname, "blue_verified": blue_verified}
    return await make_twitter_request("followers.php", params)

@mcp.tool()
async def get_tweet_info(tweet_id: str) -> Dict[str, Any] | str:
    """
    Fetches information for a specific tweet.

    Args:
        tweet_id: The ID of the tweet.
    """
    params = {"id": tweet_id}
    return await make_twitter_request("tweet.php", params)

@mcp.tool()
async def get_affiliates(screenname: str) -> Dict[str, Any] | str:
    """
    Fetches affiliates for a given user.

    Args:
        screenname: The Twitter screen name (e.g., x).
    """
    params = {"screenname": screenname}
    return await make_twitter_request("affilates.php", params) # Note: API endpoint might have a typo "affilates.php"

@mcp.tool()
async def get_user_media(screenname: str) -> Dict[str, Any] | str:
    """
    Fetches media posted by a user.

    Args:
        screenname: The Twitter screen name.
    """
    params = {"screenname": screenname}
    return await make_twitter_request("usermedia.php", params)

@mcp.tool()
async def get_retweets(tweet_id: str) -> Dict[str, Any] | str:
    """
    Fetches retweets for a specific tweet.

    Args:
        tweet_id: The ID of the tweet.
    """
    params = {"id": tweet_id}
    return await make_twitter_request("retweets.php", params)

@mcp.tool()
async def get_trends(country: str) -> Dict[str, Any] | str:
    """
    Fetches trending topics for a country.

    Args:
        country: The country for which to fetch trends (e.g., UnitedStates).
    """
    params = {"country": country}
    return await make_twitter_request("trends.php", params)

@mcp.tool()
async def search_tweets(query: str, search_type: str = "Top") -> Dict[str, Any] | str:
    """
    Searches tweets based on a query.

    Args:
        query: The search query (e.g., cybertruck).
        search_type: Type of search (e.g., Top, Latest). Defaults to "Top".
    """
    params = {"query": query, "search_type": search_type}
    return await make_twitter_request("search.php", params)

@mcp.tool()
async def get_tweet_thread(tweet_id: str) -> Dict[str, Any] | str:
    """
    Fetches a tweet thread.

    Args:
        tweet_id: The ID of the starting tweet in the thread.
    """
    params = {"id": tweet_id}
    return await make_twitter_request("tweet_thread.php", params)

@mcp.tool()
async def get_latest_replies(tweet_id: str) -> Dict[str, Any] | str:
    """
    Fetches the latest replies to a tweet.

    Args:
        tweet_id: The ID of the tweet.
    """
    params = {"id": tweet_id}
    return await make_twitter_request("latest_replies.php", params)

@mcp.tool()
async def get_list_timeline(list_id: str) -> Dict[str, Any] | str:
    """
    Fetches the timeline for a Twitter list.

    Args:
        list_id: The ID of the Twitter list.
    """
    params = {"list_id": list_id}
    return await make_twitter_request("listtimeline.php", params)

@mcp.tool()
async def search_communities_latest(query: str) -> Dict[str, Any] | str:
    """
    Searches community posts (latest) by query.

    Args:
        query: The search query.
    """
    params = {"query": query}
    return await make_twitter_request("search_communities_latest.php", params)

@mcp.tool()
async def search_communities_top(query: str) -> Dict[str, Any] | str:
    """
    Searches community posts (top) by query.

    Args:
        query: The search query.
    """
    params = {"query": query}
    return await make_twitter_request("search_communities_top.php", params)

@mcp.tool()
async def search_communities(query: str) -> Dict[str, Any] | str:
    """
    Searches communities by query.

    Args:
        query: The search query.
    """
    params = {"query": query}
    return await make_twitter_request("search_communities.php", params)

@mcp.tool()
async def get_community_timeline(community_id: str) -> Dict[str, Any] | str:
    """
    Fetches the timeline for a community.

    Args:
        community_id: The ID of the community.
    """
    params = {"community_id": community_id}
    return await make_twitter_request("community_timeline.php", params)

@mcp.tool()
async def get_list_followers(list_id: str) -> Dict[str, Any] | str:
    """
    Fetches followers of a Twitter list.

    Args:
        list_id: The ID of the Twitter list.
    """
    params = {"list_id": list_id}
    return await make_twitter_request("list_followers.php", params)

@mcp.tool()
async def get_list_members(list_id: str) -> Dict[str, Any] | str:
    """
    Fetches members of a Twitter list.

    Args:
        list_id: The ID of the Twitter list.
    """
    params = {"list_id": list_id}
    return await make_twitter_request("list_members.php", params)

# Example of how you might run this (you'll need to adapt this to your MCP framework)
async def main():
    # Example usage of one of the tools
    # Note: If tools are registered to the mcp instance, you might call them via mcp.get_user_info(...)
    # or the decorator might make them directly callable as is.
    print("Attempting to fetch user info for elonmusk...")
    user_info = await get_user_info("elonmusk", "44196397")
    print("User Info:", user_info)

    # Example: Get timeline for a user
    # print("\nAttempting to fetch timeline for elonmusk...")
    # timeline = await get_user_timeline("elonmusk")
    # print("User Timeline:", timeline)


if __name__ == "__main__":
    print("Running twitter_mcp_server.py directly for testing purposes.")
    print(f"MCP server object ('mcp') is: {type(mcp)}")
    if hasattr(mcp, 'run'):
        print("Running the FastMCP's run() method for testing.")
        mcp.run()
    else:
        print("FastMCP object does not have a run method. Executing main() for testing.")
        asyncio.run(main())

    print("\nScript execution finished.")
    print("If you ran this with 'python twitter_mcp_server.py', it was for testing.")
    print("For the actual server, use your MCP framework's CLI, e.g., 'mcp dev twitter_mcp_server.py'.")

# Helper to access the imported FastMCP or the dummy for the conditional in __main__
FastMCP_imported_or_dummy = None
try:
    from mcp.server.fastmcp.server import FastMCP as FastMCP_real
    FastMCP_imported_or_dummy = FastMCP_real
except ImportError:
    class FastMCP_dummy_check: pass
    FastMCP_imported_or_dummy = FastMCP_dummy_check
    if isinstance(mcp, FastMCP): # checks if mcp is the dummy class defined above
         FastMCP_imported_or_dummy = mcp.__class__ 