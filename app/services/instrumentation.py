from time import perf_counter
from typing import Any, Callable, Optional


def _log(logger, level: str, message: str) -> None:
    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message)
    else:
        logger.info(message)


def timed_call(
    logger,
    operation: str,
    fn: Callable[..., Any],
    *args,
    enabled: bool = True,
    log_level: str = "info",
    warn_threshold_ms: Optional[float] = None,
    suppress_error_fn: Optional[Callable[[Exception], bool]] = None,
    **kwargs,
) -> Any:
    if not enabled:
        return fn(*args, **kwargs)

    started = perf_counter()
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        if suppress_error_fn and suppress_error_fn(exc):
            raise
        elapsed_ms = (perf_counter() - started) * 1000
        _log(
            logger,
            "error",
            f"[timing] operation={operation} duration_ms={elapsed_ms:.2f} status=error error={exc.__class__.__name__}",
        )
        raise

    elapsed_ms = (perf_counter() - started) * 1000
    level_to_use = "warning" if warn_threshold_ms is not None and elapsed_ms >= warn_threshold_ms else log_level
    _log(
        logger,
        level_to_use,
        f"[timing] operation={operation} duration_ms={elapsed_ms:.2f} status=ok",
    )
    return result
