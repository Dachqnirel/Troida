import logging
import logging.config
import yaml
import os
from pathlib import Path
from dotenv import load_dotenv


def setup_logging(
    default_path='logging_config.yaml',
    default_level=logging.INFO,
    env_key='LOG_CFG'
):
    load_dotenv()
    
    # Добавьте в setup_logging()
    """Настройка логирования из YAML файла."""
    path = os.path.abspath(os.getenv(env_key))
    if os.path.exists(path):
        with open(path, 'rt', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        log_dir = Path(config['handlers']['error_file']['filename'])
        print(os.path.abspath(log_dir))
        try:
            log_dir.mkdir()
        except FileExistsError as error:
            print(error)

        # Применяем конфигурацию
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)


# Получение логгера
# logger = logging.getLogger('my_app')

# Использование
# logger.debug("Debug message")
# logger.info("Info message")
# logger.error("Error message")