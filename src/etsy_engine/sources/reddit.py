"""Reddit source (PRAW). Surfaces people's problems -> productizable needs.

We read rising/hot posts from a set of high-signal subreddits and treat post
titles as candidate trends. Reddit is great for *purchase-intent problems*
(ADHD, parenting, teachers, anxiety, homeschooling) per the spec.
"""
from __future__ import annotations

import json

from ..config import settings
from ..models import Tier, Trend
from .base import BaseSource

# High-signal communities for digital-product problems. Tune freely.
DEFAULT_SUBREDDITS = [
    "Teachers", "homeschool", "ADHD", "Parenting", "productivity",
    "GetMotivated", "PlannerAddicts", "Anxiety", "EtsySellers",
]


class RedditSource(BaseSource):
    name = "reddit"

    def __init__(self, subreddits: list[str] | None = None):
        self.subreddits = subreddits or DEFAULT_SUBREDDITS

    def fetch(self, limit: int) -> list[Trend]:
        settings.require("reddit_client_id", "reddit_client_secret")
        import praw  # imported here so the package loads without praw installed

        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        reddit.read_only = True

        per_sub = max(1, limit // len(self.subreddits))
        trends: list[Trend] = []
        for name in self.subreddits:
            try:
                for post in reddit.subreddit(name).rising(limit=per_sub):
                    payload = json.dumps({
                        "subreddit": name,
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "url": f"https://reddit.com{post.permalink}",
                    })
                    trends.append(Trend(
                        source=self.name,
                        term=post.title.strip(),
                        raw_payload=payload,
                        tier=Tier.VIRAL,
                    ))
            except Exception as e:  # one bad subreddit shouldn't kill the run
                print(f"[reddit] {name} failed: {e}")
        return trends[:limit]
