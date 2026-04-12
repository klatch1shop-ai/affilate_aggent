import os, sys, json, time
os.environ["CARD_MODEL"] = "aya-expanse:8b"
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')

from shared.utils.db import get_connection
from agents.scraper.rozetka_card_agent import process_card

def run_all():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sku FROM my_products 
        WHERE price_supplier > 0 
        AND pictures IS NOT NULL
        AND status != 'xml_ready'
        ORDER BY sku
    """)
    skus = [r["sku"] for r in cur.fetchall()]
    cur.close(); conn.close()

    logger.info(f"[NIGHT] Total SKUs to process: {len(skus)}")
    
    processed = 0
    failed = 0
    results = []

    for i, sku in enumerate(skus):
        try:
            result = process_card(sku)
            if result:
                # Зберігаємо результат в БД
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE my_products SET
                        name_uk = %s,
                        description_epicentr = %s,
                        params = %s,
                        status = 'xml_ready'
                    WHERE sku = %s
                """, (
                    result["name_ua"],
                    result["description_ua"],
                    json.dumps(result["params"]),
                    sku
                ))
                conn.commit()
                cur.close(); conn.close()
                processed += 1
                results.append(result)
            else:
                failed += 1
        except Exception as e:
            logger.error(f"[NIGHT] Error {sku}: {e}")
            failed += 1

        if (i+1) % 50 == 0:
            logger.info(f"[NIGHT] Progress: {i+1}/{len(skus)} | OK: {processed} | FAIL: {failed}")

        # Пауза між запитами щоб не перевантажувати Ollama
        time.sleep(1)

    logger.success(f"[NIGHT] Done! Processed: {processed}, Failed: {failed}")
    
    # Генеруємо фінальний XML
    from agents.scraper.xml_generator import generate_xml
    output_file = f"/home/tek/agent-system/data/rozetka_final_{int(time.time())}.xml"
    generate_xml(limit=99999, use_llm=False, output_file=output_file)
    logger.success(f"[NIGHT] XML generated: {output_file}")

if __name__ == "__main__":
    run_all()
