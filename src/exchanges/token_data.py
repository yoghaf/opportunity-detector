# src/exchanges/token_data.py

class TokenConfig:
    """
    Configuration for supported tokens.
    """
    TOKENS = {
        "USDT": {"min_borrow": 2.0, "precision": 2},
        "USDC": {"min_borrow": 2.0, "precision": 2},
        "ETH": {"min_borrow": 0.001, "precision": 6},
        "BTC": {"min_borrow": 0.0001, "precision": 8},
        # Add more tokens as needed
    }

    @classmethod
    def get_precision(cls, token):
        return cls.TOKENS.get(token, {}).get("precision", 2)

    @classmethod
    def get_min_borrow(cls, token):
        return cls.TOKENS.get(token, {}).get("min_borrow", 0.0)
