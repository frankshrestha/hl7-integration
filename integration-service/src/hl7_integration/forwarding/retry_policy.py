import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_base_seconds: float
    backoff_cap_seconds: float

    def maximum_delay_seconds(self, attempts_made: int) -> float:
        exponential_delay = self.backoff_base_seconds * 2 ** max(attempts_made - 1, 0)
        return min(self.backoff_cap_seconds, exponential_delay)

    def next_delay_seconds(self, attempts_made: int) -> float:
        upper_bound = self.maximum_delay_seconds(attempts_made)
        return random.uniform(min(self.backoff_base_seconds, upper_bound), upper_bound)
