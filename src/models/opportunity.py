from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Opportunity(BaseModel):
    currency: str
    gate_apr: float
    okx_loan_rate: float
    okx_surplus_limit: float
    net_apr: float
    available: bool
    timestamp: str