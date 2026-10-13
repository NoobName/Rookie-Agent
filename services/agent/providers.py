import json
import shutil
import sys
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import keyring

from .store import uid


@dataclass
class Reply:
    text: str = ""
    calls: list = field(default_factory=list)
    usage: dict | None = None
    assistant: dict | None = None
    usage_id: str | None = None


class ProviderAdapter(Protocol):
    async def reply(self, messages, tools, emit) -> Reply: ...


class ScriptedProvider:
    """A deterministic fixture; it never pretends to interpret arbitrary user requests."""

    def __init__(self, script=None):
        self.script = script
        self.cursor = None

    async def reply(self, messages, tools, emit):
        if not tools:
            text = "这是确定性演示模型，不具备通用问答智能。请选择真实 API，或创建演示任务验证文件与测试闭环。"
            await emit(text)
            return Reply(text, usage={"prompt_tokens": 0, "completion_tokens": 0})
        results = [
            m
            for m in messages
            if m["role"] == "tool" and json.loads(m["content"]).get("phase") != "verification"
        ]
        step = len(results) if self.cursor is None else self.cursor
        if self.script:
            if step >= len(self.script):
                return Reply(
                    "预置工作流已执行完毕，请检查真实工具证据。",
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                )
            return Reply(
                calls=[{"id": uid(), **self.script[step]}],
                usage={"prompt_tokens": 0, "completion_tokens": 0},
            )
        if step == 0:
            call = {
                "name": "files.write",
                "arguments": {
                    "path": "hello_agent.py",
                    "content": 'def greet(name):\n    return f"Hello, {name}!"\n\nif __name__ == "__main__":\n    assert greet("Agent") == "Hello, Agent!"\n    print("PASS: greet verified")\n',
                },
            }
        elif step == 1:
            result = json.loads(results[-1]["content"])
            if result["status"] != "succeeded":
                return Reply("写入未成功，停止演示。")
            interpreter = (
                shutil.which("python") if getattr(sys, "frozen", False) else sys.executable
            )
            if not interpreter:
                raise ValueError("演示需要本机 Python 解释器；后端 EXE 不能当作 Python 编译器")
            call = {
                "name": "terminal.run",
                "arguments": {"argv": [interpreter, "hello_agent.py"], "timeout": 30},
            }
        else:
            result = json.loads(results[-1]["content"])
            return Reply(
                (
                    "演示测试通过，请查看真实执行证据并验收。"
                    if result.get("exit_code") == 0
                    else "测试失败，请查看日志。"
                ),
                usage={"prompt_tokens": 0, "completion_tokens": 0},
            )
        return Reply(
            calls=[{"id": uid(), **call}], usage={"prompt_tokens": 0, "completion_tokens": 0}
        )


class OpenAICompatible:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport

    async def list_models(self):
        c = self.config
        secret = keyring.get_password("LocalAgent", c.credential_ref) if c.credential_ref else None
        if c.credential_ref and not secret:
            raise ValueError("已保存的密钥无法读取，请重新保存密钥")
        async with httpx.AsyncClient(timeout=c.timeout, transport=self.transport) as client:
            response = await client.get(
                c.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {secret}"} if secret else {},
            )
            response.raise_for_status()
            data = response.json()
        return sorted(
            {
                row["id"]
                for row in data["data"][:1000]
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
        )

    async def reply(self, messages, tools, emit):
        c = self.config
        if not c.model.strip():
            raise ValueError("模型 ID 不能为空")
        if tools and not c.tools:
            raise ValueError("该配置尚未启用原生工具能力，不能执行任务")
        secret = keyring.get_password("LocalAgent", c.credential_ref) if c.credential_ref else None
        if c.credential_ref and not secret:
            raise ValueError("已保存的密钥无法读取，请重新保存密钥")
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        body = {**c.extra, "model": c.model, "messages": messages, "stream": c.streaming}
        if tools:
            body["tools"] = tools
        if c.streaming:
            body["stream_options"] = {"include_usage": True}
        url = c.base_url.rstrip("/") + "/chat/completions"
        result = Reply()
        fragments = {}
        async with httpx.AsyncClient(timeout=c.timeout, transport=self.transport) as client:
            if not c.streaming:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                result.text = msg.get("content") or ""
                result.usage = data.get("usage")
                for call in msg.get("tool_calls") or []:
                    result.calls.append(
                        {
                            "id": call["id"],
                            "name": call["function"]["name"],
                            "arguments": json.loads(call["function"]["arguments"]),
                        }
                    )
                result.assistant = {
                    k: msg[k] for k in ("content", "tool_calls", "reasoning_content") if k in msg
                }
                result.assistant["role"] = "assistant"
                if msg.get("reasoning_content") and hasattr(emit, "reasoning"):
                    await emit.reasoning(msg["reasoning_content"])
                await emit(result.text)
                return result
            async with client.stream("POST", url, headers=headers, json=body) as response:
                response.raise_for_status()
                done = False
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        done = True
                        break
                    data = json.loads(payload)
                    if data.get("usage"):
                        result.usage = data["usage"]
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if "reasoning_content" in delta:
                        if result.assistant is None:
                            result.assistant = {"reasoning_content": ""}
                        result.assistant["reasoning_content"] += delta["reasoning_content"] or ""
                        if delta["reasoning_content"] and hasattr(emit, "reasoning"):
                            await emit.reasoning(delta["reasoning_content"])
                    if delta.get("content"):
                        result.text += delta["content"]
                        await emit(delta["content"])
                    for part in delta.get("tool_calls") or []:
                        f = fragments.setdefault(
                            part["index"], {"id": "", "name": "", "arguments": ""}
                        )
                        if part.get("id"):
                            f["id"] = part["id"]
                        f["name"] += part.get("function", {}).get("name", "")
                        f["arguments"] += part.get("function", {}).get("arguments", "")
                if not done:
                    raise ValueError("流式连接在 [DONE] 前中断；不执行不完整工具请求")
        for f in fragments.values():
            if not f["id"] or not f["name"]:
                raise ValueError("工具调用缺少标识")
            result.calls.append({**f, "arguments": json.loads(f["arguments"])})
        result.assistant = {
            **(result.assistant or {}),
            "role": "assistant",
            "content": result.text or None,
        }
        if fragments:
            result.assistant["tool_calls"] = [
                {
                    "id": f["id"],
                    "type": "function",
                    "function": {"name": f["name"], "arguments": f["arguments"]},
                }
                for f in fragments.values()
            ]
        return result
