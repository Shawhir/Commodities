"""Daily technical indicators, each with a plain reading and a technical one.

Input: a daily OHLC(V) DataFrame (columns open, high, low, close, optional volume), indexed by
date. All indicators use trailing data only. Each "signal" is a yes/no condition that the
base-rate engine can count (what happened after it in the past) and honesty-test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                         "pct_b": (close - lower) / (upper - lower), "width": (upper - lower) / mid})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """All indicator columns on the daily frame."""
    c = df["close"]
    out = pd.DataFrame(index=df.index)
    out["close"] = c
    out["rsi14"] = rsi(c)
    m = macd(c)
    out[["macd", "macd_signal", "macd_hist"]] = m[["macd", "signal", "hist"]]
    b = bollinger(c)
    out["bb_pct_b"], out["bb_width"], out["bb_upper"], out["bb_lower"] = b["pct_b"], b["width"], b["upper"], b["lower"]
    out["sma50"], out["sma200"] = c.rolling(50).mean(), c.rolling(200).mean()
    out["above_200"] = (c > out["sma200"]).astype(float).where(out["sma200"].notna())
    out["golden"] = (out["sma50"] > out["sma200"]).astype(float).where(out["sma200"].notna())
    if {"high", "low"} <= set(df.columns) and df[["high", "low"]].notna().any().all():
        out["atr14"] = atr(df)
        out["atr_pct"] = out["atr14"] / c
    out["high_252"] = c.rolling(252, min_periods=200).max()
    out["low_252"] = c.rolling(252, min_periods=200).min()
    out["from_high"] = c / out["high_252"] - 1
    out["from_low"] = c / out["low_252"] - 1
    if "volume" in df.columns and df["volume"].fillna(0).gt(0).sum() > 100:
        v = df["volume"].where(df["volume"] > 0)
        out["vol_ratio"] = v.rolling(20).mean() / v.rolling(100).mean()
    return out


def _days_since(flag: pd.Series) -> int | None:
    """Trading days since ``flag`` last changed value."""
    f = flag.dropna()
    if len(f) < 2:
        return None
    ch = f.ne(f.shift()).to_numpy()
    idx = np.flatnonzero(ch[1:])
    return int(len(f) - 1 - (idx[-1] + 1)) if len(idx) else None


def signals(ind: pd.DataFrame) -> dict[str, dict]:
    """Yes/no conditions for counting, with plain and technical names."""
    s = {
        "rsi_oversold": {"plain": "Momentum gauge very low (often called oversold)", "tech": "RSI(14) < 30",
                         "cond": ind["rsi14"] < 30},
        "rsi_overbought": {"plain": "Momentum gauge very high (often called overbought)", "tech": "RSI(14) > 70",
                           "cond": ind["rsi14"] > 70},
        "macd_up": {"plain": "Short-term trend gauge pointing up", "tech": "MACD histogram > 0 (12, 26, 9)",
                    "cond": ind["macd_hist"] > 0},
        "macd_down": {"plain": "Short-term trend gauge pointing down", "tech": "MACD histogram < 0 (12, 26, 9)",
                      "cond": ind["macd_hist"] < 0},
        "below_lower_band": {"plain": "Price below its normal daily range", "tech": "Close < lower Bollinger band (20, 2)",
                             "cond": ind["bb_pct_b"] < 0},
        "above_upper_band": {"plain": "Price above its normal daily range", "tech": "Close > upper Bollinger band (20, 2)",
                             "cond": ind["bb_pct_b"] > 1},
        "above_200": {"plain": "Price above its 200-day average", "tech": "Close > SMA200", "cond": ind["above_200"] == 1},
        "below_200": {"plain": "Price below its 200-day average", "tech": "Close < SMA200", "cond": ind["above_200"] == 0},
        "golden": {"plain": "50-day average above the 200-day (often called a golden cross)", "tech": "SMA50 > SMA200",
                   "cond": ind["golden"] == 1},
        "death": {"plain": "50-day average below the 200-day (often called a death cross)", "tech": "SMA50 < SMA200",
                  "cond": ind["golden"] == 0},
    }
    if "vol_ratio" in ind:
        s["high_volume"] = {"plain": "Trading busier than usual", "tech": "20-day / 100-day average volume > 1.3",
                            "cond": ind["vol_ratio"] > 1.3}
    return s


def readings(ind: pd.DataFrame, cur_label: str = "$") -> list[dict]:
    """Today's value of each indicator, in plain words, with the technical version."""
    last = ind.iloc[-1]
    out = []

    def add(key, name, value, plain, tech, tone):
        out.append({"key": key, "name": name, "value": value, "plain": plain, "tech": tech, "tone": tone})

    r = last["rsi14"]
    zone = "very high" if r > 70 else "very low" if r < 30 else "on the high side of normal" if r > 55 \
        else "on the low side of normal" if r < 45 else "in the middle"
    add("rsi", "Momentum gauge (0 to 100)", f"{r:.0f}",
        f"{zone[0].upper() + zone[1:]}. Above 70 is often called overbought, below 30 oversold.",
        f"RSI(14, Wilder) = {r:.1f}", "warn" if r > 70 or r < 30 else "neutral")
    h, ml = last["macd_hist"], last["macd"]
    flip = _days_since((ind["macd_hist"] > 0).astype(float).where(ind["macd_hist"].notna()))
    add("macd", "Short-term trend gauge", "pointing up" if h > 0 else "pointing down",
        f"The short-term trend has pointed {'up' if h > 0 else 'down'} for {flip} trading days." if flip is not None else
        f"The short-term trend points {'up' if h > 0 else 'down'}.",
        f"MACD(12,26,9) line {ml:.2f}, signal {last['macd_signal']:.2f}, histogram {h:+.2f}; sign unchanged for {flip} days",
        "up" if h > 0 else "down")
    pb = last["bb_pct_b"]
    pos = "above its normal range" if pb > 1 else "below its normal range" if pb < 0 else \
        "near the top of its normal range" if pb > 0.8 else "near the bottom of its normal range" if pb < 0.2 else "inside its normal range"
    add("bands", "Daily range", pos,
        f"Price is {pos} for the last 20 days. The range is {'wide' if last['bb_width'] > ind['bb_width'].median() else 'narrow'} "
        f"compared with usual, meaning {'bigger' if last['bb_width'] > ind['bb_width'].median() else 'smaller'} daily swings.",
        f"Bollinger(20, 2): %B = {pb:.2f}, bandwidth = {last['bb_width']:.3f} (median {ind['bb_width'].median():.3f})",
        "warn" if pb > 1 or pb < 0 else "neutral")
    a200 = last["above_200"]
    gap200 = last["close"] / last["sma200"] - 1
    add("ma200", "200-day average", f"{abs(gap200):.1%} {'above' if a200 == 1 else 'below'}",
        f"Price is {abs(gap200):.1%} {'above' if a200 == 1 else 'below'} its average of the last 200 trading days "
        f"({cur_label}{last['sma200']:,.0f}), a common long-term trend line.",
        f"Close / SMA200 - 1 = {gap200:+.2%}; SMA200 = {last['sma200']:.2f}", "up" if a200 == 1 else "down")
    g = last["golden"]
    since = _days_since(ind["golden"])
    add("cross", "50-day vs 200-day average", "50 above 200" if g == 1 else "50 below 200",
        f"The 50-day average is {'above' if g == 1 else 'below'} the 200-day average"
        + (f", and has been for {since} trading days." if since is not None else ".")
        + (" Traders call this a golden cross." if g == 1 else " Traders call this a death cross."),
        f"SMA50 {last['sma50']:.2f} vs SMA200 {last['sma200']:.2f}; regime unchanged for {since} days",
        "up" if g == 1 else "down")
    if "atr_pct" in last and not pd.isna(last.get("atr_pct")):
        typ = ind["atr_pct"].median()
        add("atr", "Typical daily move", f"{last['atr_pct']:.1%} a day",
            f"The price has been moving about {last['atr_pct']:.1%} a day, {'more' if last['atr_pct'] > typ else 'less'} than its usual {typ:.1%}.",
            f"ATR(14) = {last['atr14']:.2f} = {last['atr_pct']:.2%} of price; median {typ:.2%}",
            "warn" if last["atr_pct"] > 1.5 * typ else "neutral")
    add("range52", "Past year's range", f"{abs(last['from_high']):.0%} below the high",
        f"Price is {abs(last['from_high']):.0%} below the past year's highest close ({cur_label}{last['high_252']:,.0f}) "
        f"and {last['from_low']:.0%} above the lowest ({cur_label}{last['low_252']:,.0f}).",
        f"Close / max(252d) - 1 = {last['from_high']:+.2%}; close / min(252d) - 1 = {last['from_low']:+.2%}", "neutral")
    if "vol_ratio" in ind and not pd.isna(last.get("vol_ratio")):
        vr = last["vol_ratio"]
        add("volume", "Trading activity", f"{'busier' if vr > 1.1 else 'quieter' if vr < 0.9 else 'normal'}",
            f"Futures trading over the last 20 days is {vr:.0%} of its usual level. The free volume data is patchy, so this is rough.",
            f"Volume SMA20 / SMA100 = {vr:.2f}. Caution: Yahoo's front-month continuation volume is unreliable "
            f"(repeated values, contract rolls), so treat this reading as rough.",
            "warn" if vr > 1.3 else "neutral")
    return out
