import hashlib
import json
from typing import Literal
from urllib.parse import urlparse

import keyring
from pydantic import Field, model_validator

from .models import Strict


class MCPServer(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str
    enabled: bool = True
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list, max_length=100)
    url: str = ""

    @model_validator(mode="after")
    def valid(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("本地 MCP 需要启动命令")
        if self.transport == "http":
            url = urlparse(self.url)
            if url.username or url.password or url.query or url.fragment or not url.hostname:
                raise ValueError("MCP URL 不得包含凭据、查询或片段")
            if url.scheme != "https" and not (
                url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")
            ):
                raise ValueError("远程 MCP 必须使用 HTTPS")
        return self


def resolve(store, args):
    ident = args.get("server_id")
    if not ident:
        raise ValueError("MCP 调用必须选择用户已登记的 server_id")
    row = store.one("SELECT * FROM mcp_servers WHERE id=?", (ident,))
    config = json.loads(row["config"])
    if args.get("server_sha256") != hashlib.sha256(row["config"].encode()).hexdigest():
        raise PermissionError("MCP 配置已变化，原调用需重新审查授权")
    if not config["enabled"]:
        raise PermissionError("MCP 服务已禁用")
    result = {**args, **{k: config[k] for k in ("transport", "command", "args", "url")}}
    if row["credential_ref"]:
        secret = keyring.get_password("LocalAgent", row["credential_ref"])
        if not secret:
            raise ValueError("MCP 凭据无法读取，请重新保存")
        if config["transport"] != "http":
            raise ValueError("Bearer 凭据仅用于远程 HTTP MCP")
        result["_headers"] = {"Authorization": "Bearer " + secret}
    return result


def snapshot(store, args):
    if not args.get("server_id"):
        raise ValueError("MCP 调用必须选择用户已登记的 server_id")
    if set(args) - {"server_id", "server_sha256", "tool", "arguments"}:
        raise ValueError("MCP 连接命令和 URL 只能在服务设置中配置")
    row = store.one("SELECT config FROM mcp_servers WHERE id=?", (args["server_id"],))
    config = json.loads(row["config"])
    if not config["enabled"]:
        raise PermissionError("MCP 服务已禁用")
    return {
        **args,
        "server_sha256": hashlib.sha256(row["config"].encode()).hexdigest(),
    }
