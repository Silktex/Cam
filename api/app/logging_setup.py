"""
Structured logging setup with contextvars support
"""
import logging
import sys
import structlog
from structlog.contextvars import merge_contextvars


def setup_logging(log_level: str = "INFO"):
    """
    Configure structlog with JSON output and contextvars merging.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[logging.StreamHandler(sys.stdout)]
    )
