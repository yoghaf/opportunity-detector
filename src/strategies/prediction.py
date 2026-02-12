
# Pure Python implementation to avoid Pandas dependency issues
import math

def calculate_ema(data: list[dict], span: int = 10) -> list[float]:
    """
    Calculate Exponential Moving Average for a list of data points.
    Expects data to be a list of dicts with 'net_apr' key, or list of floats.
    """
    if not data:
        return []
    
    if isinstance(data[0], dict):
        # Extract values. Handle missing keys safely.
        values = [float(d.get('net_apr', 0) or 0) for d in data]
    else:
        values = [float(v or 0) for v in data]
        
    if not values:
        return []

    alpha = 2 / (span + 1)
    ema_values = []
    
    # Initialize with SMA of first element (or just first element)
    ema = values[0]
    ema_values.append(ema)
    
    for i in range(1, len(values)):
        val = values[i]
        ema = (val * alpha) + (ema * (1 - alpha))
        ema_values.append(ema)
        
    return ema_values

def analyze_trend(history: list[dict], short_span: int = 5, long_span: int = 20) -> dict:
    """
    Analyze trend based on EMA crossover or slope.
    Returns {
        'trend': 'UP' | 'DOWN' | 'FLAT',
        'strength': float (0-100),
        'short_ema': float,
        'long_ema': float
    }
    """
    if not history or len(history) < 2:
        return {'trend': 'NEUTRAL', 'strength': 0, 'short_ema': 0, 'long_ema': 0}
        
    # Sort by timestamp ascending just in case
    # Assuming history is list of dicts with 'timestamp'
    try:
        sorted_hist = sorted(history, key=lambda x: x.get('timestamp', ''))
    except:
        sorted_hist = history

    # Calculate EMAs
    short_emas = calculate_ema(sorted_hist, span=short_span)
    long_emas = calculate_ema(sorted_hist, span=long_span)
    
    if not short_emas or not long_emas:
         return {'trend': 'NEUTRAL', 'strength': 0, 'short_ema': 0, 'long_ema': 0}

    short_ema = short_emas[-1]
    
    # If not enough data for long EMA, might be inaccurate, but use what we have
    long_ema = long_emas[-1]
    
    # Simple crossover logic
    diff = short_ema - long_ema
    threshold = 0.5 # Min diff to consider trend
    
    if diff > threshold:
        trend = 'UP'
        # Strength based on divergence relative to base
        base = long_ema if long_ema != 0 else 1
        strength = min(100, (diff / base) * 1000)
    elif diff < -threshold:
        trend = 'DOWN'
        base = long_ema if long_ema != 0 else 1
        strength = min(100, (abs(diff) / base) * 1000)
    else:
        trend = 'FLAT'
        strength = 0
        
    return {
        'trend': trend,
        'strength': round(strength, 1),
        'short_ema': round(short_ema, 2),
        'long_ema': round(long_ema, 2)
    }

