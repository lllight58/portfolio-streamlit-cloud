from __future__ import annotations

import pandas as pd

from src import db


class DataFrameRepository:
    def __init__(self, table_name: str):
        self.table_name = table_name

    def read(self) -> pd.DataFrame:
        return db.read_table(self.table_name)

    def replace(self, data: pd.DataFrame) -> None:
        db.write_table(self.table_name, data)

    def append(self, data: pd.DataFrame) -> None:
        db.append_rows(self.table_name, data)
