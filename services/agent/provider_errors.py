import httpx


class BudgetExceeded(ValueError):
    pass


def explain(exc):
    if isinstance(exc, BudgetExceeded):
        return str(exc)
    # Do not expose remote response bodies, request headers, URLs or echoed secrets.
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        hint = {
            400: "请求参数无效，请检查模型 ID 和所选能力。",
            401: "认证失败，请重新保存有效 API 密钥。",
            402: "账户余额或额度不足，请检查服务商账户。",
            403: "访问被拒绝，请检查密钥权限和模型访问权限。",
            404: "接口或模型不存在，请检查 Base URL 和模型 ID。",
            422: "请求格式不被接受，请检查模型 ID、工具和视觉能力设置。",
            429: "请求过于频繁或额度受限，请稍后重试并检查账户配额。",
        }.get(status, "服务商暂时不可用，请稍后重试。" if status >= 500 else "服务商拒绝了请求，请检查接口配置。")
        return f"HTTP {status}：{hint}"
    if isinstance(exc, httpx.TimeoutException):
        return "连接或响应超时，请检查网络或增加超时秒数。"
    if isinstance(exc, httpx.RequestError):
        return "无法连接模型服务，请检查网络、代理和 Base URL。"
    if isinstance(exc, ValueError) and str(exc) in (
        "模型 ID 不能为空",
        "已保存的密钥无法读取，请重新保存密钥",
    ):
        return str(exc)
    return f"模型调用失败（{type(exc).__name__}），请检查模型能力和响应协议。"
