"""Provider-independent usage ledger and explicit user limits."""

import json
import time

from pydantic import Field

from .models import Strict
from .provider_errors import BudgetExceeded
from .providers import OpenAICompatible
from .store import dump, uid


class UsageLimits(Strict):
    token_reminder: int | None = Field(default=None, gt=0)
    cost_reminder: float | None = Field(default=None, gt=0)
    hard_tokens: int | None = Field(default=None, gt=0)
    hard_cost: float | None = Field(default=None, gt=0)


def totals(store, task_id=None):
    where = " WHERE task_id=?" if task_id else ""
    args = (task_id,) if task_id else ()
    return store.one(
        "SELECT COUNT(*) requests,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(cost),0) known_cost,SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) unknown_cost_requests,COALESCE(SUM(estimated),0) estimated_requests FROM usage"
        + where,
        args,
    )


def limits(store):
    rows = store.rows("SELECT value FROM settings WHERE key='usage_limits'")
    return UsageLimits.model_validate_json(rows[0]["value"]) if rows else UsageLimits()


def price(config, usage):
    inp = int(usage.get("prompt_tokens", 0))
    out = int(usage.get("completion_tokens", 0))
    cached = min(
        inp,
        max(
            0,
            int(
                usage.get(
                    "prompt_cache_hit_tokens",
                    usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                )
                or 0
            ),
        ),
    )
    if config.input_price is None or config.output_price is None:
        return None, cached
    cached_price = (
        config.cached_input_price if config.cached_input_price is not None else config.input_price
    )
    return (
        (inp - cached) * config.input_price + cached * cached_price + out * config.output_price
    ) / 1_000_000, cached


class MeteredProvider(OpenAICompatible):
    def __init__(self, config, store, transport=None):
        super().__init__(config, transport)
        self.store = store
        self.task_id = None

    async def reply(self, messages, tools, emit):
        store = self.store
        rule = limits(store)
        used = totals(store)
        if rule.hard_tokens and used["input_tokens"] + used["output_tokens"] >= rule.hard_tokens:
            raise BudgetExceeded("达到累计 token 硬预算；请在用量设置调整后继续")
        if rule.hard_cost:
            if (
                self.config.input_price is None
                or self.config.output_price is None
                or used["unknown_cost_requests"]
            ):
                raise BudgetExceeded(
                    "累计费用包含未知金额，无法执行硬费用预算；请补齐单价或关闭该预算"
                )
            if used["known_cost"] >= rule.hard_cost:
                raise BudgetExceeded("达到累计费用硬预算；请在用量设置调整后继续")
        started = time.time()
        reply = await super().reply(messages, tools, emit)
        usage = reply.usage or {
            "prompt_tokens": sum(len(dump(m)) for m in messages) // 3,
            "completion_tokens": len(reply.text) // 3,
        }
        cost, cached = price(self.config, usage)
        ident = uid()
        store.run(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)",
            (
                ident,
                self.task_id,
                self.config.id,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                int(reply.usage is None),
                cost,
                time.time(),
            ),
        )
        store.run("INSERT INTO usage_meta VALUES(?,?,?)", (ident, cached, time.time() - started))
        reply.usage_id = ident
        current = totals(store)
        for field, value in [
            ("token_reminder", current["input_tokens"] + current["output_tokens"]),
            ("cost_reminder", current["known_cost"]),
        ]:
            threshold = getattr(rule, field)
            if threshold and value >= threshold:
                key = "usage_notice_" + field
                marker = dump(threshold)
                previous = store.rows("SELECT value FROM settings WHERE key=?", (key,))
                if not previous or previous[0]["value"] != marker:
                    store.run("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, marker))
                    store.event(
                        self.task_id,
                        "notification",
                        {
                            "title": "累计用量达到提醒阈值",
                            "metric": field,
                            "value": value,
                            "threshold": threshold,
                        },
                    )
        return reply
