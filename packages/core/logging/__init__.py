from .logging_configure import *

# setup_logging() # конфигурация логгера.
logger: logging.Logger = logging.getLogger('my_app') # объект логера

__all__ = ["setup_logging", "logger"]