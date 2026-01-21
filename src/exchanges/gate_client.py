import gate_api
from config.settings import Config

class GateClient:
    def __init__(self):
        configuration = gate_api.Configuration(
            host="https://api.gateio.ws/api/v4",
            key=Config.GATE_API_KEY,
            secret=Config.GATE_API_SECRET
        )
        self.client = gate_api.ApiClient(configuration)
        self.earn_api = gate_api.EarnUniApi(self.client)
    
    def get_simple_earn_rates(self):
        try:
            rates = self.earn_api.list_uni_rate()
            return rates
        except Exception as e:
            print(f"Gate API Error: {e}")
            return []