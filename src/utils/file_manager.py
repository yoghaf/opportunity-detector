import pandas as pd

class FileManager:
    @staticmethod
    def save_to_csv(df, filepath):
        df.to_csv(filepath, index=False)
        print(f"Data tersimpan: {filepath} ({len(df)} records)")