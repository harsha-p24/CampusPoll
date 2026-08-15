"""Circuit breaker — prevents cascade failures in external service calls."""
import time, logging
from enum import Enum

logger = logging.getLogger(__name__)


class State(Enum):
    CLOSED    = 'closed'
    OPEN      = 'open'
    HALF_OPEN = 'half_open'


class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 5, timeout: int = 60):
        self.name      = name
        self.threshold = threshold
        self.timeout   = timeout
        self.failures  = 0
        self.last_fail = None
        self.state     = State.CLOSED

    def call(self, func, *args, **kwargs):
        if self.state == State.OPEN:
            if time.time() - self.last_fail > self.timeout:
                self.state = State.HALF_OPEN
                logger.info(f"CircuitBreaker [{self.name}] → HALF_OPEN")
            else:
                raise RuntimeError(f"CircuitBreaker [{self.name}] is OPEN")
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self):
        if self.state != State.CLOSED:
            logger.info(f"CircuitBreaker [{self.name}] → CLOSED")
        self.failures = 0
        self.state    = State.CLOSED

    def _on_failure(self):
        self.failures  += 1
        self.last_fail  = time.time()
        if self.failures >= self.threshold:
            if self.state != State.OPEN:
                logger.warning(f"CircuitBreaker [{self.name}] → OPEN after {self.failures} failures")
            self.state = State.OPEN

    @property
    def is_open(self) -> bool:
        return self.state == State.OPEN


# Pre-built breakers
email_breaker = CircuitBreaker('email',    threshold=5, timeout=120)
redis_breaker = CircuitBreaker('redis',    threshold=3, timeout=30)
db_breaker    = CircuitBreaker('database', threshold=5, timeout=60)
