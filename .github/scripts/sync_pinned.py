"""将公开 Pinned 仓库同步到 README 的“精选项目”，仅使用 Python 标准库。"""

import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


QUERY = """
query($login: String!) {
  user(login: $login) {
    pinnedItems(first: 100, types: [REPOSITORY]) {
      totalCount
      nodes { ... on Repository { nameWithOwner isPrivate } }
      pageInfo { hasNextPage }
    }
  }
}
"""
SECTION = re.compile(
    r"(^## 精选项目[^\S\n]*\n)(.*?)(?=^#{1,2} |\Z)", re.MULTILINE | re.DOTALL
)
REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")


def fetch_pinned(owner, token):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": owner}}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "readme-pinned-sync",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        error.close()
        raise ValueError(f"GitHub API 返回 HTTP {error.code}，请检查权限或限流状态") from error
    except (URLError, TimeoutError) as error:
        raise ValueError(f"GitHub API 请求失败：{error}") from error
    except ValueError as error:
        raise ValueError("GitHub API 未返回有效 JSON") from error

    # GraphQL 即使 HTTP 200 也可能返回错误或部分数据；此时禁止更新 README。
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("GitHub GraphQL 返回错误，未更新 README；请检查用户、权限或 API 状态")
    try:
        pinned = payload["data"]["user"]["pinnedItems"]
        nodes = pinned["nodes"]
        if (
            not isinstance(nodes, list)
            or pinned["pageInfo"]["hasNextPage"] is not False
            or pinned["totalCount"] != len(nodes)
        ):
            raise ValueError("Pinned 数据不完整，拒绝更新 README")
        repositories = []
        for node in nodes:
            name = node["nameWithOwner"]
            if not isinstance(name, str) or not REPOSITORY.fullmatch(name):
                raise ValueError("Pinned 仓库标识无效，拒绝更新 README")
            if not isinstance(node["isPrivate"], bool):
                raise ValueError("Pinned 仓库可见性无效，拒绝更新 README")
            # 资料 README 是公开展示，不将 token 可见的私有仓库写入其中。
            if not node["isPrivate"]:
                repositories.append(name)
        if len({name.lower() for name in repositories}) != len(repositories):
            raise ValueError("Pinned 数据包含重复仓库，拒绝更新 README")
        return repositories
    except (KeyError, TypeError) as error:
        raise ValueError("GitHub API 响应缺少有效的 Pinned 数据") from error


def render_section(repositories):
    lines = ["", '<div align="center">', ""]
    for repository in repositories:
        owner, name = repository.split("/")
        query = urlencode({
            "username": owner,
            "repo": name,
            "theme": "tokyonight",
            "hide_border": "true",
            "border_radius": "10",
        })
        lines.extend([
            f'<a href="https://github.com/{repository}">',
            f'  <img src="https://github-stats-extended.vercel.app/api/pin/?{query}" alt="{name}" />',
            "</a>",
        ])
    lines.extend(["", "</div>", "", ""])
    return "\n".join(lines)


def sync_readme(path, repositories):
    # 字节级保留章节之外的内容；无差异时不执行写入。
    original = path.read_bytes()
    readme = original.decode("utf-8")
    sections = list(SECTION.finditer(readme))
    if len(sections) != 1:
        raise ValueError("README 必须恰好包含一个“## 精选项目”章节")
    section = sections[0]
    updated = (
        readme[:section.start(2)]
        + render_section(repositories)
        + readme[section.end(2):]
    ).encode("utf-8")
    if updated == original:
        return False
    path.write_bytes(updated)
    return True


def main():
    try:
        owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
        token = os.environ.get("GITHUB_TOKEN")
        if not owner or not token:
            raise ValueError("缺少 GITHUB_REPOSITORY_OWNER 或 GITHUB_TOKEN")
        repositories = fetch_pinned(owner, token)
        changed = sync_readme(Path("README.md"), repositories)
        message = (
            f"已同步 {len(repositories)} 个公开 Pinned 仓库到 README 精选项目。"
            if changed else "精选项目与公开 Pinned 一致，无需修改。"
        )
        print(message)
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8", newline="\n") as output:
                output.write(f"## Pinned 同步\n\n{message}\n")
                output.writelines(f"- `{name}`\n" for name in repositories)
        return 0
    except (ValueError, OSError) as error:
        print(f"Pinned 同步失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
