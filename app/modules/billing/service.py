# app/modules/billing/service.py
class BudgetExceededError(Exception):
    pass

COST_PER_1K_TOKENS = {
    'gpt-4o': {'input': 0.005, 'output': 0.015},
    'gpt-4o-mini': {'input': 0.00015, 'output': 0.0006},
    'text-embedding-3-small': {'input': 0.00002, 'output': 0},
    'text-embedding-3-large': {'input': 0.00013, 'output': 0},
    'liquid/lfm-2.5-2.6b:free': {'input': 0.0, 'output': 0.0},
    'liquid/lfm-3-1.7b:free': {'input': 0.0, 'output': 0.0},
    'nvidia/nemotron-3-ultra-550b-a55b:free': {'input': 0.0, 'output': 0.0},
    'deepseek/deepseek-v4-flash:free': {'input': 0.0, 'output': 0.0},
    'nvidia/nemotron-3.5-lightning:free': {'input': 0.0, 'output': 0.0},
    'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free': {'input': 0.0, 'output': 0.0},
    'baidu/ernie-5.5-flash-preview:free': {'input': 0.0, 'output': 0.0},
}

class BillingService:
    async def get_monthly_cost(self, user_id):
        return 0.0

    async def log_usage(self, user_id, model, tokens_in, tokens_out, cost):
        pass

    async def check_and_log_usage(
        self, user, model: str, tokens_in: int, tokens_out: int
    ) -> None:
        rates = COST_PER_1K_TOKENS.get(model, {'input': 0.0, 'output': 0.0})
        cost = (
            tokens_in / 1000 * rates['input'] +
            tokens_out / 1000 * rates['output']
        )
        monthly_cost = await self.get_monthly_cost(user.id)
        if monthly_cost + cost > user.monthly_budget_usd:
            raise BudgetExceededError('Monthly AI budget exceeded')
        await self.log_usage(user.id, model, tokens_in, tokens_out, cost)
