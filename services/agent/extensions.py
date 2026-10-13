"""Optional capabilities. No plugin may bypass the caller's PolicyEngine."""

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Literal

from .models import Strict
from .policy import inside


class BrowserArgs(Strict):
    action: Literal["open", "observe", "fill", "click", "submit", "download", "upload", "close"]
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    observation: str | None = None
    output: str | None = None
    input: str | None = None


class BrowserTools:
    def __init__(self):
        self.sessions = {}
        self.playwright = None
        self.channel = os.getenv("AGENT_BROWSER_CHANNEL")

    async def launch(self, task, human):
        profile = inside(task["spec"]["workspace"], ".agent-browser-profile")
        for ident, session in list(self.sessions.items()):
            if ident != task["id"] and session.get("profile") == str(profile):
                if session.get("human"):
                    raise ValueError("此工作区浏览器正由用户接管，请先结束接管")
                await session["context"].close()
                self.sessions.pop(ident, None)
        options = {"user_data_dir": str(profile), "headless": not human, "accept_downloads": True}
        if self.channel:
            options["channel"] = self.channel
        return await self.playwright.chromium.launch_persistent_context(**options)

    async def handoff(self, task, human):
        tid = task["id"]
        old = self.sessions.pop(tid, None)
        url = old["page"].url if old else "about:blank"
        if old:
            await old["context"].close()
        if self.playwright is None:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
        try:
            context = await self.launch(task, human)
        except Exception:
            # Restore headless operation when a visible browser cannot start.
            if old:
                context = await self.launch(task, False)
                page = await context.new_page()
                self.sessions[tid] = {
                    "context": context,
                    "page": page,
                    "observation": None,
                    "url": None,
                    "human": False,
                }
                if url.startswith(("http://", "https://")):
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            raise RuntimeError(
                "无法启动可见浏览器；请检查 Chromium 安装，或配置 AGENT_BROWSER_CHANNEL=msedge。任务保持暂停，未执行页面动作。"
            )
        page = context.pages[0] if context.pages else await context.new_page()
        self.sessions[tid] = {
            "context": context,
            "page": page,
            "observation": None,
            "url": None,
            "human": human,
            "profile": str(inside(task["spec"]["workspace"], ".agent-browser-profile")),
        }
        if url.startswith(("http://", "https://")):
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {
            "human": human,
            "detail": (
                "已交给用户，可在独立浏览器登录；任务保持暂停。"
                if human
                else "已收回浏览器，旧观察失效；请审查计划后继续任务。"
            ),
        }

    async def run(self, task, args):
        if self.playwright is None:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
        tid = task["id"]
        action = args["action"]
        if action == "close":
            session = self.sessions.pop(tid, None)
            if session:
                await session["context"].close()
            return {"output": "独立浏览器会话已关闭"}
        if tid not in self.sessions:
            if action != "open":
                raise ValueError("先打开独立浏览器")
            context = await self.launch(task, False)
            self.sessions[tid] = {
                "context": context,
                "page": await context.new_page(),
                "observation": None,
                "url": None,
                "profile": str(inside(task["spec"]["workspace"], ".agent-browser-profile")),
            }
        s = self.sessions[tid]
        page = s["page"]
        if s.get("human"):
            raise PermissionError("浏览器已交给用户；请先在界面结束接管")
        if action == "open":
            from urllib.parse import urlparse

            if urlparse(args["url"] or "").scheme not in ("http", "https"):
                raise ValueError("只允许 HTTP(S) URL")
            await page.goto(args["url"], wait_until="domcontentloaded", timeout=30000)
        elif action != "observe":
            if (
                not args["observation"]
                or args["observation"] != s["observation"]
                or page.url != s["url"]
            ):
                raise ValueError("页面观察已过期，请重新 observe")
            s["observation"] = None
            if not args["selector"]:
                raise ValueError("需要可验证的页面 selector")
            locator = page.locator(args["selector"])
            if await locator.count() != 1:
                raise ValueError("定位结果必须唯一")
            if action == "fill":
                await locator.fill(args["text"] or "", timeout=10000)
            elif action == "upload":
                if not args.get("input"):
                    raise ValueError("上传需要工作区文件路径")
                source = inside(task["spec"]["workspace"], args["input"])
                if not source.is_file():
                    raise ValueError("上传文件不存在")
                await locator.set_input_files(str(source), timeout=10000)
            elif action == "click":
                is_submit = await locator.evaluate(
                    "el => !!el.closest('form') && ((el.tagName==='BUTTON' && el.type!=='button') || el.type==='submit')"
                )
                if is_submit:
                    raise ValueError("这是表单提交，请使用 submit 动作单独授权")
                await locator.click(timeout=10000)
            elif action == "submit":
                await locator.click(timeout=10000)
            elif action == "download":
                if not args["output"]:
                    raise ValueError("下载需要工作区输出路径")
                output = inside(task["spec"]["workspace"], args["output"])
                if output.exists():
                    raise ValueError("下载不覆盖已有文件")
                async with page.expect_download(timeout=15000) as info:
                    await locator.click()
                await (await info.value).save_as(str(output))
        s["observation"] = secrets.token_hex(16)
        s["url"] = page.url
        controls = await page.locator("input,button,a,textarea,select").evaluate_all(
            "els => els.slice(0,100).map(el => ({tag:el.tagName,id:el.id,name:el.getAttribute('name'),type:el.getAttribute('type'),text:(el.innerText||el.getAttribute('aria-label')||'').slice(0,160)}))"
        )
        return {
            "output": (await page.locator("body").inner_text())[:30000],
            "controls": controls,
            "source": {"url": page.url, "title": await page.title(), "retrieved": time.time()},
            "observation": s["observation"],
            "artifacts": [args["output"]] if action == "download" else [],
        }

    async def close(self):
        for session in self.sessions.values():
            await session["context"].close()
        self.sessions.clear()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None


class DesktopArgs(Strict):
    action: Literal["windows", "observe", "focus", "screenshot", "click", "type", "hotkey"]
    hwnd: int | None = None
    control_id: int | None = None
    text: str | None = None
    keys: str | None = None
    observation: str | None = None
    output: str | None = None


class DesktopTools:
    def __init__(self):
        self.stopped = True
        self.observation = None
        self.controls = []
        self.target = None
        self.hook = None
        self.ready = None
        self.registered = False

    def arm(self):
        import sys

        if sys.platform != "win32":
            raise RuntimeError("仅 Windows 支持桌面控制")
        self.stopped = True
        self.observation = None
        if not self.hook or not self.hook.is_alive():
            import threading

            self.ready = threading.Event()
            self.hook = threading.Thread(target=self._hotkey, daemon=True)
            self.hook.start()
        if not self.ready.wait(3) or not self.registered:
            raise RuntimeError("紧急停止快捷键注册失败；保持禁止输入")
        self.stopped = False

    def _hotkey(self):
        import ctypes
        from ctypes import wintypes

        user = ctypes.windll.user32
        # Ctrl+Alt+F12: registration failure keeps all input disabled.
        self.registered = bool(user.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, 0x7B))
        self.ready.set()
        if not self.registered:
            self.stop()
            return
        msg = wintypes.MSG()
        while user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:
                self.stop()

    def stop(self):
        self.stopped = True
        self.observation = None

    def run(self, args):
        import pythoncom

        pythoncom.CoInitialize()
        try:
            return self._run(args)
        finally:
            pythoncom.CoUninitialize()

    def _run(self, args):
        import ctypes

        from pywinauto import Desktop

        action = args["action"]
        desktop = Desktop(backend="uia")
        if action == "windows":
            return {
                "output": [
                    {"hwnd": w.handle, "title": w.window_text()}
                    for w in desktop.windows()
                    if w.is_visible()
                ]
            }
        if not args["hwnd"]:
            raise ValueError("必须明确选择目标窗口 hwnd")
        window = desktop.window(handle=args["hwnd"]).wrapper_object()
        if action not in ("observe", "screenshot"):
            if self.stopped:
                raise PermissionError("桌面控制已停止；请人工重新启用")
            if args["observation"] != self.observation or not self.observation:
                raise ValueError("需要新的 UIA 观察")
            if time.monotonic() - self.observed_at > 30:
                self.stop()
                raise ValueError("UIA 观察超过 30 秒，请重新观察")
            if self.target != args["hwnd"] or (
                action != "focus" and ctypes.windll.user32.GetForegroundWindow() != args["hwnd"]
            ):
                self.stop()
                raise ValueError("目标窗口焦点改变，已交还用户控制")
            rect = (
                window.rectangle().left,
                window.rectangle().top,
                window.rectangle().right,
                window.rectangle().bottom,
            )
            if rect != self.rect:
                self.stop()
                raise ValueError("窗口位置改变，需重新观察")
            if ctypes.windll.user32.GetDpiForWindow(args["hwnd"]) != self.dpi:
                self.stop()
                raise ValueError("目标窗口 DPI 改变，请重新观察")
            self.observation = None
            if action == "focus":
                window.set_focus()
            elif action in ("click", "type"):
                i = args["control_id"]
                if i is None or i < 0 or i >= len(self.controls):
                    raise ValueError("控件 ID 无效")
                control = self.controls[i]
                if action == "click":
                    control.click_input()
                else:
                    control.set_edit_text(args["text"] or "")
            elif action == "hotkey":
                allowed = {
                    "ENTER": "{ENTER}",
                    "TAB": "{TAB}",
                    "ESC": "{ESC}",
                    "CTRL+A": "^a",
                    "CTRL+S": "^s",
                }
                if args["keys"] not in allowed:
                    raise ValueError("不支持的快捷键")
                window.type_keys(allowed[args["keys"]])
        if action == "screenshot":
            if not args.get("output"):
                raise ValueError("截图必须指定工作区输出路径")
            window.capture_as_image().save(args["output"], format="PNG")
        self.controls = window.descendants()[:200]
        self.target = args["hwnd"]
        self.rect = (
            window.rectangle().left,
            window.rectangle().top,
            window.rectangle().right,
            window.rectangle().bottom,
        )
        self.observation = secrets.token_hex(16)
        self.observed_at = time.monotonic()
        self.dpi = ctypes.windll.user32.GetDpiForWindow(args["hwnd"])
        return {
            "output": [
                {
                    "id": i,
                    "title": c.window_text(),
                    "type": c.element_info.control_type,
                    "enabled": c.is_enabled(),
                }
                for i, c in enumerate(self.controls)
            ],
            "observation": self.observation,
            "target": args["hwnd"],
            "stopped": self.stopped,
        }
