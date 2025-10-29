import logging
import logging.config
import yaml
import os
from pathlib import Path



def setup_logging(
    default_path='./logging_config.yaml',
    default_level=logging.INFO,
):
    """
    Конфигурация логгинга.
    """
    with open(default_path, encoding='utf8', mode='r') as f:
        config = yaml.safe_load(f)
    log_error: Path = Path(str(config['handlers']['error_file']['filename']))
    log_error.parent.mkdir(parents=True, exist_ok=True)
    log_error.touch(exist_ok=True)

    logging.config.dictConfig(config)
