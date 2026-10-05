#!/usr/bin/env python3
"""
Pulls profile numbers from GitHub's GraphQL API into data/stats.json.

Two rules worth keeping:
  1. One query, not twenty. REST would need a request per repo plus pagination.
  2. Never start from scratch. Yesterday's numbers are loaded first and only
     overwritten by what this run actually fetched, so a GitHub hiccup leaves
     the profile one day stale instead of showing a wall of zeros.
"""

import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
CFG = json.loads((HERE / "config.json").read_text())
USER = os.environ.get("PROFILE_USER") or CFG["github_user"]
TOKEN = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")

PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    merged: pullRequests(states: MERGED) { totalCount }
    contributionsCollection { contributionYears }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        forkCount
        languages(first: 20) { edges { size node { name } } }
      }
    }
  }
}
"""


def graphql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"bearer {TOKEN}",
                 "Content-Type": "application/json",
                 "User-Agent": "profile-console"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if res.get("errors"):
        raise RuntimeError("; ".join(e["message"] for e in res["errors"]))
    return res["data"]


def years_query(years):
    """contributionsCollection covers at most one year per request, so ask for
    every year at once using GraphQL aliases."""
    parts = [f'''
    y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") {{
      contributionCalendar {{
        totalContributions
        weeks {{ contributionDays {{ date contributionCount }} }}
      }}
    }}''' for y in years]
    return "query($login: String!) { user(login: $login) {" + "".join(parts) + " } }"


def streaks(days, today):
    longest = run = 0
    for d in sorted(d for d in days if d <= today):
        run = run + 1 if days[d] > 0 else 0
        longest = max(longest, run)

    current = 0
    d = datetime.date.fromisoformat(today)
    # the job runs at midday, so an empty today must not reset the streak
    if days.get(d.isoformat(), 0) == 0:
        d -= datetime.timedelta(days=1)
    while days.get(d.isoformat(), 0) > 0:
        current += 1
        d -= datetime.timedelta(days=1)
    return current, longest


def fetch(today):
    u = graphql(PROFILE_Q, {"login": USER})["user"]
    repos = u["repositories"]["nodes"]

    sizes = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            sizes[e["node"]["name"]] = sizes.get(e["node"]["name"], 0) + e["size"]
    total = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    langs = [[n, round(s * 100 / total, 1)] for n, s in top]
    rest = round(100 - sum(p for _, p in langs), 1)
    if rest > 0.05:
        langs.append(["Other", rest])

    years = u["contributionsCollection"]["contributionYears"]
    cal = graphql(years_query(years), {"login": USER})["user"]
    days, this_year, all_time = {}, 0, 0
    for y in years:
        c = cal[f"y{y}"]["contributionCalendar"]
        all_time += c["totalContributions"]
        if y == datetime.date.fromisoformat(today).year:
            this_year = c["totalContributions"]
        for wk in c["weeks"]:
            for d in wk["contributionDays"]:
                days[d["date"]] = d["contributionCount"]

    cur, longest = streaks(days, today)
    created = u["createdAt"][:10]
    yrs = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(created)).days // 365

    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "forks": sum(r["forkCount"] for r in repos),
        "repos": u["repositories"]["totalCount"],
        "followers": u["followers"]["totalCount"],
        "prs": u["pullRequests"]["totalCount"],
        "merged": u["merged"]["totalCount"],
        "this_year": this_year,
        "all_time": all_time,
        "streak": cur,
        "longest": longest,
        "since": f'{datetime.date.fromisoformat(created).strftime("%b %Y")} ({yrs}y)',
        "languages": langs,
    }


def main():
    if not TOKEN:
        sys.exit("error: set PROFILE_TOKEN or GITHUB_TOKEN")
    if USER.startswith("YOUR_"):
        sys.exit("error: set github_user in config.json")

    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "stats.json"
    stats = json.loads(out.read_text()) if out.exists() else {}

    today = datetime.date.today().isoformat()
    try:
        stats.update(fetch(today))
    except Exception as ex:
        if not stats:
            sys.exit(f"error: first fetch failed, nothing to fall back on: {ex}")
        print(f"warning: GitHub fetch failed, keeping previous stats: {ex}", file=sys.stderr)

    stats["synced"] = today
    out.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"wrote {out} for @{USER}")


if __name__ == "__main__":
    main()
