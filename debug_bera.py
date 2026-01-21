from src.exchanges.okx_client import OKXClient

client = OKXClient()
data = client.get_loan_limit()
print("Raw BERA data:")

for item in data:
    if isinstance(item, dict) and 'records' in item:
        for record in item['records']:
            if record.get('ccy') == 'BERA':
                print(f"Record: {record}")
                print(f"Daily rate: {record.get('rate', 0) * 100}%")
                print(f"APY (calc): {record.get('rate', 0) * 100 * 365}%")
                print(f"Surplus: {record.get('surplusLmt', 0)}")