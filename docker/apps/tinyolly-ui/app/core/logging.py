"""Logging configuration"""

import logging
import sys

from ..config import settings


def setup_logging():
    """Configure logging with stdout handler"""
    # Set up basic logging to stdout
    # OTLP handler and LoggingInstrumentor are added in telemetry.py
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


logger = logging.getLogger(__name__)
