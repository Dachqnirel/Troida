from dotenv import load_dotenv
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
load_dotenv()

@dataclass(init=False)
class DirectoriesForReports:
    # путь к директории, которая содержит проверенные на аномалии отчёты
    checkedReportsDirectory: Path
    
    # булева переменная, указывающая, была ли создана директория или уже существовала. Если создан True, если существовала False
    checkedReportsDirectoryWasCreated: bool
    
    # путь к директории, которая содержит непроверенные на аномалии отчёты
    uncheckedReportsDirectory: Path
        
    # булева переменная, указывающая, была ли создана директория или уже существовала. Если создан True, если существовала False
    uncheckedReportsDirectoryWasCreated: bool = True

DIRECTORY_UNCHECKED_REPORTS: str = Path(os.getenv('REPORTS_DIRECTORY_UNCHECKED'))
DIRECTORY_CHECKED_REPORTS: str = Path(os.getenv('REPORTS_DIRECTORY_CHECKED'))

paths: list[str] = [DIRECTORY_UNCHECKED_REPORTS, DIRECTORY_CHECKED_REPORTS]

def createDirectoriesFromEnvVar(paths: list[str] = paths) -> DirectoriesForReports:
    """Создание директорий для хранения отчётов. Отчёты делятся на два типа: "Проверенные на аномалии и непроверенные"

    Args:
        paths (list[str]): список с путями, которые необходимо создать (если их нет)

    Returns:
       DirectoriesForReports: data-class.
    """
    current_date_str_utc = datetime.now(tz=timezone.utc).strftime('%d.%m.%Y')
    report: DirectoriesForReports =  DirectoriesForReports()
    for index, path in enumerate(paths):
        currentPath: Path = Path(path) / current_date_str_utc
        is_path_exists: bool = currentPath.exists()
        if not is_path_exists:
            currentPath.mkdir(parents=True)
        match index:
            case 0:
                report.uncheckedReportsDirectory = currentPath
                report.uncheckedReportsDirectoryWasCreated = not is_path_exists
            case 1:
                report.checkedReportsDirectory = currentPath
                report.checkedReportsDirectoryWasCreated = is_path_exists
                
    return report

createDirectoriesFromEnvVar([DIRECTORY_UNCHECKED_REPORTS,DIRECTORY_CHECKED_REPORTS])
