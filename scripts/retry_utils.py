import time


def with_retry(fn, retries=3, delay=1.0, catch=Exception):
    """Call fn(), retrying up to `retries` times on transient errors.

    Backs off exponentially: delay seconds before attempt 2, 2*delay before attempt 3.
    Re-raises the last exception if all attempts fail.
    """
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except catch as exc:
            if attempt == retries:
                raise
            wait = delay * (2 ** (attempt - 1))
            print(f'  [retry {attempt}/{retries}] {type(exc).__name__}: {exc} — retrying in {wait:.0f}s')
            time.sleep(wait)
