"""Stable error feedback for model repair and user intervention."""


def describe_tool_error(tool, result):
    message = str(result.get("error") or "")
    lowered = message.lower()
    if "超时" in message or "timeout" in lowered:
        kind, suggestion = "timeout", "检查进程是否等待输入或陷入循环，调整命令后再尝试。"
    elif "发生变化" in message or "已变化" in message or "sha256" in lowered:
        kind, suggestion = "version_conflict", "重新读取当前文件与 SHA-256，再根据最新内容修改。"
    elif "PermissionError" in message or "授权" in message or "越出" in message:
        kind, suggestion = "permission", "检查任务授权和工作区范围；不得绕过用户权限。"
    elif "FileNotFoundError" in message or "不存在" in message:
        kind, suggestion = "not_found", "检查工作区、文件路径或可执行程序是否存在。"
    elif "ValidationError" in message or "ValueError" in message or "参数" in message:
        kind, suggestion = "invalid_arguments", "根据工具定义和错误提示修正参数，不要原样重复调用。"
    elif result.get("exit_code") not in (None, 0):
        kind, suggestion = "command_exit", "检查标准错误和输出，修正命令或代码后再运行。"
    else:
        kind, suggestion = (
            "tool_error",
            "检查错误详情与上下文，尝试有依据的修正；无法处理时向用户说明。",
        )
    detail = (result.get("stderr") or result.get("stdout") or "")[-4000:]
    return {
        "type": kind,
        "tool": tool,
        "message": message[:2000] or f"命令退出码 {result.get('exit_code', '未知')}",
        "exit_code": result.get("exit_code"),
        "details": detail,
        "suggestion": suggestion,
        "requires_user": kind == "permission",
    }
