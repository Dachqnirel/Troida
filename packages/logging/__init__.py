from .logging_configure import *

setup_logging()
logger = logging.getLogger('my_app')

__all__ = ["logger"]