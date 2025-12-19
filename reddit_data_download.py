import asyncpraw
import json
import os
from dotenv import load_dotenv
import logging
import time

load_dotenv()

# --- Configure Logging ---
LOG_FILE = "reddit_data.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) 

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG) 

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

# --- Helper Function ---
async def _fetch_comments(submission):
    """Helper function to fetch and process comments."""
    comments_data = []
    if submission.num_comments > 0:
        try:
            comments = await submission.comments()
            if comments:
                await comments.replace_more(limit=None)
                for comment in comments.list():
                    if comment and comment.body not in ("[removed]", "[deleted]"):
                        comments_data.append({"body": comment.body})
        except Exception as e:
            logger.error(f"Error fetching comments for {submission.title}: {e}")
    else:
        comments_data.append({"body": "Comments are disabled!"})
    return comments_data

# --- Data Fetching Functions ---
async def get_posts_by_flair(search_term, data_dir="data"):
    """Fetches posts by flair, saves to JSON, and returns data."""
    user_agent = "Android Scrapper 4.0 by Rugved"
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=user_agent,
    )

    os.makedirs(data_dir, exist_ok=True)
    filename = f"{search_term.replace(' ', '_')}.json"
    filepath = os.path.join(data_dir, filename)

    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                logger.info(f"Loading data from {filepath}")
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error reading {filepath}, fetching from Reddit: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error reading {filepath}: {e}")
            return []

    try:
        subreddit = await reddit.subreddit("android_beta")
        logger.info(f"Fetching posts for flair: {search_term}")
        submissions = subreddit.search(f'flair_name:"{search_term}"')
        all_posts_data = []

        async for submission in submissions:
            logger.debug(f"Processing submission: {submission.title}")
            post_data = {
                'title': submission.title,
                'text': submission.selftext,
                'comments': await _fetch_comments(submission)
            }
            all_posts_data.append(post_data)

        with open(filepath, "w") as f:
            json.dump(all_posts_data, f, indent=4)
            logger.info(f"Data saved to {filepath}")

        return all_posts_data

    except asyncpraw.exceptions.RedditAPIException as e:
        logger.error(f"Reddit API Error: {e}")
        return []
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        return []
    finally:
        await reddit.close()


async def get_post_by_url(post_url):
    """Fetches a single Reddit post and its comments given its URL."""
    try:
        reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="Android Scrapper 4.0 by Rugved",
        )
        submission = await reddit.submission(url=post_url)
        post_data = {
            'title': submission.title,
            'text': submission.selftext,
            'comments': await _fetch_comments(submission)
        }
        await reddit.close()
        return [post_data]

    except asyncpraw.exceptions.RedditAPIException as e:
        logger.error(f"Reddit API Error fetching post by URL: {e}")
        return []
    except Exception as e:
        logger.exception(f"Error fetching post by URL: {e}")
        return []

async def get_posts_by_keywords_and_time(subreddit_name, keywords, time_filter):
    """Fetches posts from a subreddit matching keywords and a time filter."""
    try:
        reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="Android Scrapper 4.0 by Rugved",
        )
        subreddit = await reddit.subreddit(subreddit_name)
        query = f"{keywords}"
        logger.info(f"Fetching posts from r/{subreddit_name} with keywords: '{keywords}', time_filter: {time_filter}")
        submissions = subreddit.search(query, time_filter=time_filter)
        all_posts_data = []

        async for submission in submissions:
            post_data = {
                'title': submission.title,
                'text': submission.selftext,
                'comments': await _fetch_comments(submission)
            }
            all_posts_data.append(post_data)
        await reddit.close()
        return all_posts_data

    except asyncpraw.exceptions.RedditAPIException as e:
        logger.error(f"Reddit API Error: {e}")
        return []
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        return []

# --- Main Data Fetching Function which works as a Router ---
async def get_reddit_data(data_type, identifier, time_filter=None, data_dir="data"):
    """
    Fetches Reddit data based on the specified data type and identifier.

    Args:
        data_type (str): 'flair', 'url', or 'keywords'.
        identifier (str): The flair, URL, or keywords.
        time_filter (str, optional): Time filter for keywords search.
        data_dir (str): The directory to save data (for flair).

    Returns:
        list: The fetched Reddit data.
    """
    if data_type == "flair":
        return await get_posts_by_flair(identifier, data_dir)
    elif data_type == "url":
        return await get_post_by_url(identifier)
    elif data_type == "keywords":
        return await get_posts_by_keywords_and_time("android_beta", identifier, time_filter)
    else:
        logger.error(f"Invalid data_type: {data_type}")
        return []