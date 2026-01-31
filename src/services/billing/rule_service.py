"""
BillingRule 查找逻辑

查找顺序（与 .plans/humming-seeking-marble.md 一致）：
1) Model（Provider 级）→ 2) GlobalModel（默认）

注意：
- CLI 在计费域等同于 chat：billing_rules.task_type 不含 "cli"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from src.models.database import BillingRule, GlobalModel, Model

TaskType = Literal["chat", "cli", "video", "image", "audio"]


def effective_rule_task_type(task_type: str) -> str:
    """CLI 在计费规则域里恒等于 chat。"""
    t = (task_type or "").lower()
    return "chat" if t == "cli" else t


@dataclass(frozen=True)
class BillingRuleLookupResult:
    rule: BillingRule
    scope: Literal["model", "global"]
    effective_task_type: str


class BillingRuleService:
    @staticmethod
    def find_rule(
        db: Session,
        *,
        provider_id: str | None,
        model_name: str,
        task_type: str,
    ) -> BillingRuleLookupResult | None:
        effective_task = effective_rule_task_type(task_type)

        global_model = (
            db.query(GlobalModel)
            .filter(
                GlobalModel.name == model_name,
                GlobalModel.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not global_model:
            return None

        # 1) Provider Model 覆盖
        if provider_id:
            model_obj = (
                db.query(Model)
                .filter(
                    Model.provider_id == provider_id,
                    Model.global_model_id == global_model.id,
                    Model.is_active == True,  # noqa: E712
                )
                .first()
            )
            if model_obj:
                rule = (
                    db.query(BillingRule)
                    .filter(
                        BillingRule.model_id == model_obj.id,
                        BillingRule.task_type == effective_task,
                        BillingRule.is_enabled == True,  # noqa: E712
                    )
                    .first()
                )
                if rule:
                    return BillingRuleLookupResult(
                        rule=rule,
                        scope="model",
                        effective_task_type=effective_task,
                    )

        # 2) GlobalModel 默认规则
        rule = (
            db.query(BillingRule)
            .filter(
                BillingRule.global_model_id == global_model.id,
                BillingRule.task_type == effective_task,
                BillingRule.is_enabled == True,  # noqa: E712
            )
            .first()
        )
        if rule:
            return BillingRuleLookupResult(
                rule=rule, scope="global", effective_task_type=effective_task
            )

        return None
