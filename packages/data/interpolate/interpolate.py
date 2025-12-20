import pandas as pd

def interpolate_missing_intervals(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or 'data_status' not in df.columns:
        return df
    df_local = df.copy()
    df_local['datetime'] = pd.to_datetime(df_local['datetime'])
    df_local = df_local.sort_values('datetime').reset_index(drop=True)
    missing_mask = df_local['data_status'] == 'missing'
    if not missing_mask.any():
        return df_local
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    numeric_cols_present = [col for col in numeric_cols if col in df_local.columns]
    if not numeric_cols_present:
        return df_local
    for col in numeric_cols_present:
        df_local[col] = pd.to_numeric(df_local[col], errors='coerce')
    df_local = df_local.set_index('datetime')
    df_local[numeric_cols_present] = df_local[numeric_cols_present].interpolate(
        method='time',
        limit_direction='both'
    )
    df_local.reset_index(inplace=True)
    df_local.loc[missing_mask, 'data_status'] = 'interpolated'
    return df_local
