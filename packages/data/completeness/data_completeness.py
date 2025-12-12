import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pandas import DataFrame

class DataCompletenessValidator:
    """
    Класс для проверки полноты и целостности временных рядов свечных данных
    """
    
    @staticmethod
    def validate_data_completeness_by_interval(
        df: DataFrame,
        interval_minutes: int,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Проверяет полноту данных с учетом указанного интервала из конфига
        
        Args:
            df: DataFrame с колонкой 'datetime'
            interval_minutes: ожидаемый интервал между свечами в минутах (60=1H, 120=2H, 240=4H)
            from_date: начальная дата периода (из конфига, но игнорируем фактическое время)
            to_date: конечная дата периода (из конфига, но игнорируем фактическое время)
        
        Returns:
            Словарь с метриками полноты данных
        """
        if df.empty or 'datetime' not in df.columns:
            return {
                'is_complete': False,
                'expected_count': 0,
                'actual_count': 0,
                'missing_intervals': 0,
                'completeness_percentage': 0.0,
                'missing_days_count': 0,
                'missing_intervals_list': [],
                'missing_days_list': []
            }
        
        # Убедимся, что datetime в правильном формате
        df = df.copy()
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        
        # Определяем период из фактических данных
        # ИГНОРИРУЕМ from_date и to_date из конфига как просили
        start_date = df['datetime'].min()
        end_date = df['datetime'].max()
        
        # Генерируем временные метки в соответствии с указанным интервалом
        # но начиная с фактической первой временной метки в данных
        full_timeline = DataCompletenessValidator._generate_timeline_by_interval(
            start_date, end_date, interval_minutes
        )
        
        # Находим фактические временные метки
        actual_timestamps = set(df['datetime'])
        
        # Находим пропущенные интервалы
        missing_intervals = [ts for ts in full_timeline if ts not in actual_timestamps]
        
        # Вычисляем метрики
        expected_count = len(full_timeline)
        actual_count = len(actual_timestamps)
        missing_count = len(missing_intervals)
        completeness_percentage = (actual_count / expected_count) * 100 if expected_count > 0 else 0
        
        # Находим дни с пропусками
        missing_days = DataCompletenessValidator._get_missing_days(missing_intervals)
        
        return {
            'is_complete': missing_count == 0,
            'expected_count': expected_count,
            'actual_count': actual_count,
            'missing_intervals': missing_count,
            'completeness_percentage': completeness_percentage,
            'missing_days_count': len(missing_days),
            'missing_intervals_list': missing_intervals,
            'missing_days_list': missing_days,
            'period_start': start_date,
            'period_end': end_date,
            'interval_minutes': interval_minutes
        }
    
    @staticmethod
    def _generate_timeline_by_interval(
        start_date: datetime, 
        end_date: datetime, 
        interval_minutes: int
    ) -> List[datetime]:
        """
        Генерирует временную шкалу в соответствии с указанным интервалом
        
        Для 1H: каждый час от начала до конца
        Для 2H: каждые 2 часа от начала до конца
        Для 4H: каждые 4 часа от начала до конца
        """
        timeline = []
        
        # Приводим start_date к ближайшему интервалу
        # Для 2H интервала: если данные начинаются в 06:00, то это уже правильное время
        # Для 1H интервала: тоже самое
        
        current_time = start_date
        while current_time <= end_date:
            timeline.append(current_time)
            current_time += timedelta(minutes=interval_minutes)
        
        return timeline
    
    @staticmethod
    def _get_missing_days(missing_intervals: List[datetime]) -> List[str]:
        """Возвращает список дней с пропущенными интервалами"""
        missing_days = set()
        for interval in missing_intervals:
            day_str = interval.strftime('%Y-%m-%d')
            missing_days.add(day_str)
        
        return sorted(list(missing_days))
    
    @staticmethod
    def print_terminal_report(report: Dict[str, any], ticker: str, interval: str) -> None:
        """Выводит красивый отчёт о полноте данных в терминал"""
        status_icon = "✅" if report['is_complete'] else "⚠️"
        
        print(f"{status_icon} АКТИВ: {ticker} (интервал: {interval})")
        print(f"   Период (фактический): {report['period_start'].strftime('%Y-%m-%d %H:%M')} - {report['period_end'].strftime('%Y-%m-%d %H:%M')}")
        print(f"   Интервал из конфига: {report['interval_minutes']} минут")
        print(f"   Ожидаемое количество свечей: {report['expected_count']}")
        print(f"   Фактическое количество свечей: {report['actual_count']}")
        print(f"   Пропущенных свечей: {report['missing_intervals']}")
        print(f"   Процент полноты: {report['completeness_percentage']:.2f}%")
        print(f"   Количество дней с пропусками: {report['missing_days_count']}")
        
        if not report['is_complete'] and report['missing_days_list']:
            print(f"   Дни с пропусками: {', '.join(report['missing_days_list'][:5])}"
                  f"{'...' if len(report['missing_days_list']) > 5 else ''}")
        
        if not report['is_complete'] and report['missing_intervals_list']:
            print(f"   Примеры пропущенных свечей:")
            for interval_time in report['missing_intervals_list'][:3]:
                print(f"     - {interval_time}")
            if len(report['missing_intervals_list']) > 3:
                print(f"     ... и ещё {len(report['missing_intervals_list']) - 3} пропусков")
        
        # Дополнительная информация о распределении пропусков
        if not report['is_complete'] and report['missing_intervals_list']:
            # Анализируем, какие часы чаще всего пропускаются
            hour_counts = {}
            for interval in report['missing_intervals_list']:
                hour = interval.hour
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            if hour_counts:
                print(f"   Распределение пропусков по часам (UTC):")
                for hour in sorted(hour_counts.keys()):
                    count = hour_counts[hour]
                    percentage = (count / report['missing_intervals']) * 100
                    print(f"     - {hour:02d}:00: {count} пропусков ({percentage:.1f}%)")
        
        print()
    
    @staticmethod
    def insert_missing_intervals_in_dataframe(
        df: DataFrame,
        completeness_report: Dict[str, any]
    ) -> DataFrame:
        """
        Вставляет пропущенные интервалы в DataFrame как строки с NaN значениями
        и добавляет колонку data_status
        """
        if completeness_report['missing_intervals'] == 0:
            # Если пропусков нет, просто добавляем колонку
            df_marked = df.copy()
            df_marked['data_status'] = 'present'
            return df_marked
        
        # Создаем DataFrame для пропущенных интервалов
        missing_data = []
        for missing_dt in completeness_report['missing_intervals_list']:
            missing_row = {
                'datetime': missing_dt,
                'open': np.nan,
                'high': np.nan, 
                'low': np.nan,
                'close': np.nan,
                'volume': np.nan,
                'data_status': 'missing'
            }
            missing_data.append(missing_row)
        
        missing_df = pd.DataFrame(missing_data)
        
        # Добавляем пометку к существующим данным
        df_marked = df.copy()
        df_marked['data_status'] = 'present'
        
        # Объединяем существующие данные с пропущенными интервалами
        combined_df = pd.concat([df_marked, missing_df], ignore_index=True)
        
        # Сортируем по дате
        combined_df = combined_df.sort_values('datetime').reset_index(drop=True)
        
        return combined_df
    
    @staticmethod
    def generate_missing_data_report(report: Dict[str, any]) -> str:
        """Генерирует текстовый отчёт о пропущенных данных"""
        report_lines = []
        report_lines.append("ОТЧЁТ О ПРОПУЩЕННЫХ ДАННЫХ")
        report_lines.append("=" * 50)
        report_lines.append(f"Период: {report['period_start']} - {report['period_end']}")
        report_lines.append(f"Интервал: {report['interval_minutes']} минут")
        report_lines.append(f"Ожидаемое количество свечей: {report['expected_count']}")
        report_lines.append(f"Фактическое количество свечей: {report['actual_count']}")
        report_lines.append(f"Пропущенных свечей: {report['missing_intervals']}")
        report_lines.append(f"Процент полноты: {report['completeness_percentage']:.2f}%")
        report_lines.append(f"Количество дней с пропусками: {report['missing_days_count']}")
        
        if report['missing_days_list']:
            report_lines.append("\nДни с пропущенными данными:")
            for day in report['missing_days_list']:
                report_lines.append(f"  - {day}")
        
        if report['missing_intervals_list']:
            report_lines.append(f"\nПропущенные свечи (первые 20):")
            for interval in report['missing_intervals_list'][:20]:
                report_lines.append(f"  - {interval}")
        
        # Добавляем анализ по часам
        if report['missing_intervals_list']:
            hour_counts = {}
            for interval in report['missing_intervals_list']:
                hour = interval.hour
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            if hour_counts:
                report_lines.append(f"\nРаспределение пропусков по часам (UTC):")
                for hour in sorted(hour_counts.keys()):
                    count = hour_counts[hour]
                    percentage = (count / report['missing_intervals']) * 100
                    report_lines.append(f"  - {hour:02d}:00: {count} пропусков ({percentage:.1f}%)")
        
        return "\n".join(report_lines)