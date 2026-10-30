"""AI limits and explicitly versioned Standard pricing (USD nanodollars)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AiConfig:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    model: str = "gpt-6.1-sol"
    monthly_limit_usd: int = 50
    max_input_tokens: int = 24_000
    max_output_tokens: int = 4_000
    max_requests: int = 6
    timeout_seconds: int = 120
    concurrency: int = 2

    def __post_init__(self) -> None:
        # A new model needs an explicit pricing review before spending is enabled.
        if self.model != "gpt-6.1-sol" or not 1 <= self.monthly_limit_usd <= 50:
            raise ValueError("Unsupported AI model or budget")
        if not (1 <= self.max_input_tokens <= 24_000 and 1 <= self.max_output_tokens <= 4_000):
            raise ValueError("Invalid AI token limits")
        if not (1 <= self.max_requests <= 6 and 1 <= self.timeout_seconds <= 120):
            raise ValueError("Invalid AI execution limits")


INPUT_NUSD = 2_000
CACHED_INPUT_NUSD = 100
OUTPUT_NUSD = 10_000
# Use the highest supported cache-write price for reservations. Requests do not
# opt into paid extended caching; unknown/new usage fields retain the reserve.
MAX_INPUT_NUSD = 5_000
USD_NANO = 1_000_000_000
