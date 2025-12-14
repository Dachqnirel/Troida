# rolling_catboost.py
# ==============================================================
# Общий модуль для задач:
#  - загрузка данных (CSV → OHLCV),
#  - построение выборки скользящими окнами (walk-forward),
#  - сплит по времени,
#  - обучение CatBoostClassifier для мультикласса,
#  - обработка unseen-классов на валидации.
#
# ВАЖНО: индикаторо-специфичные вещи (признаки, метрики, разметка, сетка параметров, CLI) не входят в этот файл, чтобы не дублировать логику.
# ==============================================================


import numpy as np
import pandas as pd
from typing import Callable, Optional, Tuple, Dict, Sequence
from catboost import CatBoostClassifier, CatBoostError


# ВСПОМОГАТЕЛЬНОЕ: безопасная автокорреляция лаг=1 - аккуратно считает автокорреляцию ряда с лагом 1 (ACF1) (меряем «память» доходностей — часто близко к нулю, но полезно как фича).
def acf1_safe(x: pd.Series) -> float:
    x = pd.Series(x).dropna()
    if len(x) < 3:
        return 0.0
    x0, x1 = x.iloc[:-1], x.iloc[1:]
    den = float(x.std(ddof=0)) ** 2 * (len(x) - 1)
    if den <= 0:
        return 0.0
    return float(((x0 - x.mean()) * (x1 - x.mean())).sum() / den)


def sharpe_and_sum(ret: pd.Series) -> Tuple[float, float]:
    """Shared strategy metric: (Sharpe, Sum)."""
    r = pd.Series(ret).dropna()
    if len(r) < 3:
        return 0.0, float(r.sum())
    mu = float(r.mean())
    sd = float(r.std(ddof=0))
    return mu / (sd + 1e-12), float(r.sum())


# ЗАГРУЗКА CSV: аккуратно читаем OHLCV и приводим к единому виду - удаляет «Unnamed»/пустые колонки, находит колонку времени, сортирует по времени, приводит имена к нижнему регистру и возвращает DataFrame с хотя бы close (open/high/low/volume — опционально).
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # 1) Удаляем «Unnamed»/пустые колонки (например, индекс 0,1,2,...)
    bad = df.columns.astype(str).str.match(r'Unnamed: ?\d*|^$')
    if bad.any():
        df = df.loc[:, ~bad]

    # 2) Находим колонку времени
    time_cols = [c for c in df.columns if str(c).lower() in ("time","timestamp","date","datetime")]
    tcol = time_cols[0] if len(time_cols) else df.columns[0]
    df["__dt__"] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    df = df.dropna(subset=["__dt__"]).set_index("__dt__").sort_index()

    # 3) Приводим имена к нижнему регистру
    df.columns = [str(c).lower() for c in df.columns]

    # 4) Проверяем наличие close
    if "close" not in df.columns:
        raise ValueError("В CSV нет колонки 'close'")

    # 5) Оставляем только полезные столбцы, но НЕ выкидываем отсутствующие — ими займёмся в фичах
    keep = [c for c in ["open","high","low","close","volume"] if c in df.columns]
    return df[keep]


# ДАТАСЕТ: формируем (X, y) скользящими окнами - идём по истории с шагом step — на каждом шаге вызываем label_fn, который ДОЛЖЕН вернуть (X_t, y_t) для текущего t.
# label_fn: Callable[[pd.DataFrame, int, int, int], Tuple[pd.Series, int]]
#            принимает (df, start, lookback, horizon) и возвращает (X, y).
def build_dataset(df: pd.DataFrame, lookback: int = 1000, horizon: int = 100, step: int = 50, label_fn: Callable[[pd.DataFrame, int, int, int], Tuple[pd.Series, int]] | None = None) -> Tuple[pd.DataFrame, pd.Series]:
    if label_fn is None:
        raise ValueError("Нужно передать label_fn, который формирует (X, y) для каждого окна.")
    X_rows, y_rows = [], []
    for t in range(lookback, len(df) - horizon, step):
        X_t, y_t = label_fn(df, t, lookback, horizon)
        X_rows.append(X_t)
        y_rows.append(y_t)
    X_df = pd.DataFrame(X_rows).reset_index(drop=True)
    y_ser = pd.Series(y_rows, name="label")
    return X_df, y_ser


# Сплит по времени  (всегда train = ранние примеры; valid = поздние)
def time_split_by_ratio(X: pd.DataFrame, y: pd.Series, valid_ratio: float = 0.2) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    n_train = int(len(X) * (1.0 - valid_ratio))
    Xtr, ytr = X.iloc[:n_train], y.iloc[:n_train]
    Xva, yva = X.iloc[n_train:], y.iloc[n_train:]
    return Xtr, ytr, Xva, yva


# Диагностика unseen-классов в валидации: если в валидации есть классы, которых нет в обучении — фильтруем их.
def prepare_eval_set_unseen(X_val: pd.DataFrame, y_val: pd.Series, y_train: pd.Series) -> Optional[Tuple[pd.DataFrame, pd.Series]]:
    train_classes = set(y_train.unique())
    test_classes  = set(y_val.unique())
    unseen_in_test = sorted(c for c in test_classes if c not in train_classes)
    if unseen_in_test:
        print(f"[INFO] В тесте есть классы, отсутствующие в обучении: {unseen_in_test}")
        mask = y_val.isin(list(train_classes))
        Xva2, yva2 = X_val[mask], y_val[mask]
        if len(Xva2) == 0:
            print("[INFO] Все тестовые классы отсутствуют в обучении. Обучим без eval_set.")
            return None
        else:
            print(f"[INFO] Оставлено в валидации после фильтра: {len(Xva2)} из {len(X_val)}")
            return (Xva2, yva2)
    else:
        return (X_val, y_val)


# Базовые (разумные) дефолты CatBoost для мультикласса c ранней остановкой
def default_catboost_params() -> dict:
    return dict(
        iterations=4000,            # много итераций + ранняя остановка
        depth=6,
        learning_rate=0.03,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        od_type="Iter",
        od_wait=200,
        use_best_model=True,
        random_seed=42,
        allow_writing_files=True,    # разрешить создавать catboost_info с логами метрик (learn_error.tsv, time_left.log и т.п.) - требуется для построения catboost виджета (learn/test)
        train_dir="catboost_info",
        verbose=100,
        # балансировка классов (если поддерживается версией CatBoost)
        # умеренная регуляризация/стохастичность
        l2_leaf_reg=20,
        random_strength=1.5,
        rsm=0.8,
        bootstrap_type="Bayesian",
        bagging_temperature=1.0,
    )


# Явно считаем веса классов как 1/freq, чтобы вручную балансировать выборку.
def compute_class_weights(y: pd.Series) -> dict:
    """Compute class weights as 1/freq for CatBoost."""
    counts = y.value_counts()
    total = len(y)
    n_cls = len(counts)
    return {cls: total / (n_cls * cnt) for cls, cnt in counts.items()}


# Построить итоговые параметры: стандарт + произвольные переопределения (key=val). Пример: overrides_str='depth=5,iterations=2500,learning_rate=0.04' (маленький парсер key=val, чтобы без изменений кода можно было подстроить CatBoost из CLI/ноутбука.)
def build_catboost_params(overrides_str: str | None = None) -> dict:
    params = default_catboost_params()
    if overrides_str and overrides_str.strip():
        for token in overrides_str.split(","):
            token = token.strip()
            if not token or "=" not in token:
                continue
            k, v = token.split("=", 1)
            k, v = k.strip(), v.strip()
            if v.lower() in ("true","false"):
                params[k] = (v.lower() == "true")
            else:
                try:
                    if "." in v:
                        params[k] = float(v)
                    else:
                        params[k] = int(v)
                except Exception:
                    params[k] = v
    return params


# Обучение CatBoostClassifier с учётом eval_set и ранней остановки. Возвращает (model, holdout_acc или None).
def fit_catboost_multiclass(X_train: pd.DataFrame, y_train: pd.Series, X_val: Optional[pd.DataFrame] = None, y_val: Optional[pd.Series] = None, params: Optional[dict] = None, plot_fit: bool = False):
    params = (params or default_catboost_params()).copy()
    # Подстраховка: если параметр не поддерживается установленной версией CatBoost, убираем его.
    params.pop("auto_class_weights", None)
    if "class_weights" not in params:
        params["class_weights"] = compute_class_weights(y_train)
    model = CatBoostClassifier(**params)

    fit_kwargs = {}
    if plot_fit:
        fit_kwargs["plot"] = True

    def _train(kwargs):
        if X_val is None or y_val is None or len(X_val) == 0:
            model.fit(X_train, y_train, **kwargs)
            return model, None
        model.fit(X_train, y_train, eval_set=(X_val, y_val), **kwargs)
        pred = model.predict(X_val).flatten().astype(int)
        acc = float((pred == y_val.values).mean())
        return model, acc

    try:
        return _train(fit_kwargs)
    except (CatBoostError, ImportError, ModuleNotFoundError) as exc:
        if plot_fit:
            print("[WARN] CatBoost plot viewer unavailable (install ipywidgets/traitlets?): {exc}. Retrying without plots.")
            fit_kwargs.pop("plot", None)
            return _train(fit_kwargs)
        raise
