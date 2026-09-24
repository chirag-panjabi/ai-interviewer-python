"""
github_service.py - GitHub Profile & Repository Extraction
Fetches public repository metadata and cleans READMEs for prompt grounding.
Includes in-memory TTL caching to avoid GitHub unauthenticated rate limits.
"""
import re
import time
from typing import Optional, Dict, Any, List
import httpx

# In-memory cache: { username: (data, timestamp) }
_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
CACHE_TTL_SECONDS = 600  # 10 minutes


def parse_github_username(input_str: str) -> str:
    """Extracts username from raw handle or full GitHub URL."""
    clean = input_str.strip().lower()
    clean = re.sub(r"^https?://(www\.)?github\.com/", "", clean)
    clean = clean.split("/")[0]  # Take first path segment
    return clean or "candidate"


async def fetch_github_profile(username_or_url: str, github_token: Optional[str] = None) -> Dict[str, Any]:
    """Fetches user profile and their top public repositories."""
    username = parse_github_username(username_or_url)

    # Check cache first
    now = time.time()
    if username in _cache:
        cached_data, cached_time = _cache[username]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_data

    headers = {"User-Agent": "AI-Interviewer-Python"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    async with httpx.AsyncClient(headers=headers, timeout=8.0) as client:
        try:
            # 1. Fetch user profile
            user_resp = await client.get(f"https://api.github.com/users/{username}")
            if user_resp.status_code == 404:
                return {
                    "username": username,
                    "name": username,
                    "bio": "Software Engineer",
                    "avatarUrl": f"https://github.com/{username}.png",
                    "repos": [],
                }

            user_data = user_resp.json() if user_resp.status_code == 200 else {}

            # 2. Fetch public repositories (sorted by updated)
            repos_resp = await client.get(
                f"https://api.github.com/users/{username}/repos",
                params={"sort": "updated", "per_page": 12},
            )
            repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

            parsed_repos = []
            if isinstance(repos_data, list):
                for r in repos_data:
                    if r.get("fork"):
                        continue  # Skip forked repos to highlight original work
                    parsed_repos.append(
                        {
                            "name": r.get("name", ""),
                            "description": r.get("description") or "No description provided.",
                            "language": r.get("language") or "Code",
                            "stars": r.get("stargazers_count", 0),
                            "updatedAt": r.get("updated_at", ""),
                        }
                    )

            result = {
                "username": user_data.get("login", username),
                "name": user_data.get("name") or user_data.get("login", username),
                "bio": user_data.get("bio") or "Software Engineer",
                "avatarUrl": user_data.get("avatar_url") or f"https://github.com/{username}.png",
                "repos": parsed_repos[:8],
            }

            _cache[username] = (result, now)
            return result

        except Exception as e:
            # Fallback on network errors or rate limits
            return {
                "username": username,
                "name": username,
                "bio": "Software Engineer",
                "avatarUrl": f"https://github.com/{username}.png",
                "repos": [],
            }


async def fetch_repo_readme(username: str, repo_name: str, github_token: Optional[str] = None) -> str:
    """Fetches, sanitizes, and truncates a repository README."""
    if not username or not repo_name:
        return ""

    headers = {"User-Agent": "AI-Interviewer-Python"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    branches = ["main", "master"]
    readme_content = ""

    async with httpx.AsyncClient(headers=headers, timeout=6.0) as client:
        for branch in branches:
            try:
                url = f"https://raw.githubusercontent.com/{username}/{repo_name}/{branch}/README.md"
                resp = await client.get(url)
                if resp.status_code == 200:
                    readme_content = resp.text
                    break
            except Exception:
                continue

    if not readme_content:
        return f"Repository {repo_name} by {username}."

    # Sanitization: strip markdown image tags, HTML tags, and non-printable characters
    clean = re.sub(r"!\[.*?\]\(.*?\)", "", readme_content)  # Strip ![alt](url)
    clean = re.sub(r"<[^>]+>", "", clean)                   # Strip HTML tags
    clean = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", clean)  # Non-printable ASCII
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    # Truncate strictly to 2,000 characters to prevent prompt bloat and injection
    return clean[:2000]
