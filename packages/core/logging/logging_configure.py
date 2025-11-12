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
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - [%(pathname)s:%(lineno)d]', datefmt='%Y-%m-%d %H:%M:%S', level=logging.ERROR)
    
    config_file_is_open: bool = False
    
    for filepath in default_path:
        try:
            with open(filepath, encoding='utf8', mode='r') as f:
                config = yaml.safe_load(f)
            logging.info(f'Файл конфигурации логгера {filepath} успешно открыт')
            config_file_is_open = True
        except FileNotFoundError as error:
            logging.warning(f'Ошибка при открытии файла конфигурации логгера {filepath}. Ошибка: {error}')
    
    if not config_file_is_open:
        exit(1)
    
    log_error: Path = Path(str(config['handlers']['error_file']['filename']))
    log_error.parent.mkdir(parents=True, exist_ok=True)
    log_error.touch(exist_ok=True)

    logging.config.dictConfig(config)
