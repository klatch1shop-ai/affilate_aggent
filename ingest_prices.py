import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", 5432),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

DOWNLOADS_PATH = "/home/tekken/Завантажене"

def load_to_db(partial_name):
    # Шукаємо файли .xlsx або .csv
    files = [f for f in os.listdir(DOWNLOADS_PATH) if partial_name in f and (f.endswith('.xlsx') or f.endswith('.csv'))]
    if not files:
        print(f"❌ Файл з назвою '{partial_name}' не знайдено.")
        return

    file_path = os.path.join(DOWNLOADS_PATH, files[0])
    print(f"🔄 Знайдено: {files[0]}. Починаю імпорт...")

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, skiprows=3)
        else:
            # Для Excel файлів
            df = pd.read_excel(file_path, skiprows=3, engine='openpyxl')
        
        # Колонки: 1-Артикул, 2-Товар, 5-РРЦ
        df = df.iloc[:, [1, 2, 5]]
        df.columns = ['sku', 'name', 'price_rrc']
        df = df.dropna(subset=['sku', 'name'])

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        count = 0
        for _, row in df.iterrows():
            sku_val = str(row['sku']).strip()
            if not sku_val or sku_val == "nan": continue
            
            try:
                cur.execute("""
                    INSERT INTO products (sku, name_uk, status)
                    VALUES (%s, %s, 'new')
                    ON CONFLICT (sku) DO UPDATE SET name_uk = EXCLUDED.name_uk;
                """, (sku_val, str(row['name'])))
                count += 1
            except:
                continue

        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Успішно завантажено {count} позицій з {files[0]}")
    except Exception as e:
        print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    load_to_db('Прайс 19,01,2026')
    load_to_db('Прайс ОБЛАДНАННЯ 19,01,2026')
