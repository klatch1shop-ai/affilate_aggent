import os, sys, json, asyncio, psycopg2, redis
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))
app = Server('agent-system-mcp')

def get_db():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'), cursor_factory=RealDictCursor
    )

def get_redis():
    return redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'), port=int(os.getenv('REDIS_PORT', 6379)), decode_responses=True)

def dt_fix(rows):
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime): r[k] = v.isoformat()
    return rows

@app.list_tools()
async def list_tools():
    return [
        types.Tool(name='log_event', description='Записати подію в лог',
            inputSchema={'type':'object','properties':{
                'agent_name':{'type':'string'},'level':{'type':'string'},
                'message':{'type':'string'},'metadata':{'type':'object'}
            },'required':['agent_name','message']}),
        types.Tool(name='get_logs', description='Отримати логи',
            inputSchema={'type':'object','properties':{
                'agent_name':{'type':'string'},'limit':{'type':'integer'}
            }}),
        types.Tool(name='get_agents_status', description='Статус агентів',
            inputSchema={'type':'object','properties':{}}),
        types.Tool(name='create_alert', description='Створити сповіщення',
            inputSchema={'type':'object','properties':{
                'source':{'type':'string'},'title':{'type':'string'},
                'message':{'type':'string'},'level':{'type':'string'}
            },'required':['source','title']}),
        types.Tool(name='get_alerts', description='Отримати сповіщення',
            inputSchema={'type':'object','properties':{
                'only_unread':{'type':'boolean'},'limit':{'type':'integer'}
            }}),
        types.Tool(name='save_products', description='Зберегти товари',
            inputSchema={'type':'object','properties':{
                'products':{'type':'array','items':{'type':'object'}}
            },'required':['products']}),
        types.Tool(name='get_products', description='Отримати товари',
            inputSchema={'type':'object','properties':{
                'marketplace':{'type':'string'},'limit':{'type':'integer'}
            }}),
        types.Tool(name='push_task', description='Відправити задачу агенту',
            inputSchema={'type':'object','properties':{
                'agent_name':{'type':'string'},'task':{'type':'object'}
            },'required':['agent_name','task']}),
        types.Tool(name='get_queue_stats', description='Статистика черг',
            inputSchema={'type':'object','properties':{}}),
        types.Tool(name='run_sql', description='Виконати SQL запит',
            inputSchema={'type':'object','properties':{
                'query':{'type':'string'}
            },'required':['query']}),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == 'log_event':
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute('SELECT id FROM agents WHERE name = %s', (arguments['agent_name'],))
            row = cur.fetchone()
            cur.execute('INSERT INTO event_logs (agent_id, level, message, metadata) VALUES (%s,%s,%s,%s)',
                (row['id'] if row else None, arguments.get('level','INFO'),
                 arguments['message'], Json(arguments.get('metadata',{}))))
            conn.commit(); cur.close(); conn.close()
            return [types.TextContent(type='text', text='OK')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'get_logs':
        try:
            conn = get_db(); cur = conn.cursor()
            agent = arguments.get('agent_name')
            limit = arguments.get('limit', 50)
            if agent:
                cur.execute('SELECT el.*, a.name as agent_name FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id WHERE a.name=%s ORDER BY el.created_at DESC LIMIT %s', (agent, limit))
            else:
                cur.execute('SELECT el.*, a.name as agent_name FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id ORDER BY el.created_at DESC LIMIT %s', (limit,))
            rows = dt_fix([dict(r) for r in cur.fetchall()])
            cur.close(); conn.close()
            return [types.TextContent(type='text', text=json.dumps(rows, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'get_agents_status':
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute('SELECT name, type, status, updated_at FROM agents ORDER BY name')
            rows = dt_fix([dict(r) for r in cur.fetchall()])
            cur.close(); conn.close()
            return [types.TextContent(type='text', text=json.dumps(rows, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'create_alert':
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute('INSERT INTO alerts (source, title, message, level) VALUES (%s,%s,%s,%s)',
                (arguments['source'], arguments['title'],
                 arguments.get('message',''), arguments.get('level','INFO')))
            conn.commit(); cur.close(); conn.close()
            return [types.TextContent(type='text', text='OK')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'get_alerts':
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute('SELECT * FROM alerts WHERE is_read=%s ORDER BY created_at DESC LIMIT %s',
                (arguments.get('only_unread', True), arguments.get('limit', 20)))
            rows = dt_fix([dict(r) for r in cur.fetchall()])
            cur.close(); conn.close()
            return [types.TextContent(type='text', text=json.dumps(rows, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'save_products':
        try:
            conn = get_db(); cur = conn.cursor(); saved = 0
            for p in arguments.get('products', []):
                cur.execute('INSERT INTO products (external_id,marketplace,title,price,old_price,url,category,seller,in_stock,data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (external_id,marketplace) DO UPDATE SET price=EXCLUDED.price,old_price=EXCLUDED.old_price,in_stock=EXCLUDED.in_stock,scraped_at=NOW()',
                    (p.get('external_id',''), p.get('marketplace',''), p.get('title',''),
                     p.get('price',0), p.get('old_price',0), p.get('url',''),
                     p.get('category',''), p.get('seller',''), p.get('in_stock',True), Json(p.get('data',{}))))
                saved += 1
            conn.commit(); cur.close(); conn.close()
            return [types.TextContent(type='text', text=f'Saved {saved} products')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'get_products':
        try:
            conn = get_db(); cur = conn.cursor()
            mp = arguments.get('marketplace')
            limit = arguments.get('limit', 50)
            if mp:
                cur.execute('SELECT * FROM products WHERE marketplace=%s ORDER BY scraped_at DESC LIMIT %s', (mp, limit))
            else:
                cur.execute('SELECT * FROM products ORDER BY scraped_at DESC LIMIT %s', (limit,))
            rows = dt_fix([dict(r) for r in cur.fetchall()])
            cur.close(); conn.close()
            return [types.TextContent(type='text', text=json.dumps(rows, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'push_task':
        try:
            r = get_redis()
            task = arguments.get('task', {})
            task['timestamp'] = datetime.now().isoformat()
            queue = f"queue:{arguments['agent_name']}"
            r.rpush(queue, json.dumps(task))
            return [types.TextContent(type='text', text=f'Pushed to {queue}')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'get_queue_stats':
        try:
            r = get_redis()
            stats = {a: r.llen(f'queue:{a}') for a in ['orchestrator','scraper','marketing','developer','finance','efficiency']}
            return [types.TextContent(type='text', text=json.dumps(stats))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    elif name == 'run_sql':
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute(arguments['query'])
            if cur.description:
                rows = dt_fix([dict(r) for r in cur.fetchall()])
                result = rows
            else:
                conn.commit()
                result = {'affected': cur.rowcount}
            cur.close(); conn.close()
            return [types.TextContent(type='text', text=json.dumps(result, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'ERROR: {e}')]

    return [types.TextContent(type='text', text=f'Unknown tool: {name}')]

async def main():
    logger.info('[MCP SERVER] Starting...')
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
