"""
File System MCP сервер — дає агентам доступ до документації
Аналог ідеї з PDF: агенти читають структуровані JSON/MD файли
замість галюцинацій
"""
import os, sys, json, glob
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import asyncio

app = Server("filesystem-mcp")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "../../shared/skills")
DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")

@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="read_skill", description="Прочитати скіл агента",
            inputSchema={"type":"object","properties":{
                "skill_name":{"type":"string"},
                "agent_name":{"type":"string"}
            },"required":["skill_name"]}),
        types.Tool(name="list_skills", description="Список всіх скілів",
            inputSchema={"type":"object","properties":{
                "agent_name":{"type":"string"}
            }}),
        types.Tool(name="read_api_doc", description="Прочитати документацію API маркетплейсу",
            inputSchema={"type":"object","properties":{
                "marketplace":{"type":"string","enum":["prom","rozetka","epicentr"]}
            },"required":["marketplace"]}),
        types.Tool(name="save_knowledge", description="Зберегти знання в базу",
            inputSchema={"type":"object","properties":{
                "filename":{"type":"string"},
                "content":{"type":"string"},
                "category":{"type":"string"}
            },"required":["filename","content"]}),
        types.Tool(name="read_knowledge", description="Прочитати збережені знання",
            inputSchema={"type":"object","properties":{
                "filename":{"type":"string"}
            },"required":["filename"]}),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "read_skill":
        agent = arguments.get("agent_name","")
        skill = arguments.get("skill_name","")
        paths = glob.glob(f"{DOCS_DIR}/{agent}/{skill}.md") or \
                glob.glob(f"{DOCS_DIR}/**/{skill}.md", recursive=True)
        if paths:
            with open(paths[0]) as f:
                return [types.TextContent(type="text", text=f.read())]
        return [types.TextContent(type="text", text=f"Скіл не знайдено: {skill}")]

    elif name == "list_skills":
        agent = arguments.get("agent_name","")
        pattern = f"{DOCS_DIR}/{agent}/*.md" if agent else f"{DOCS_DIR}/**/*.md"
        files = glob.glob(pattern, recursive=True)
        skills = []
        for f in files:
            with open(f) as fp:
                first = fp.readline().strip().lstrip("# ")
            skills.append({"file": os.path.basename(f), "description": first})
        return [types.TextContent(type="text", text=json.dumps(skills, ensure_ascii=False))]

    elif name == "read_api_doc":
        mp = arguments.get("marketplace","")
        path = f"{DOCS_DIR}/scraper/{mp}_api.md"
        if os.path.exists(path):
            with open(path) as f:
                return [types.TextContent(type="text", text=f.read())]
        return [types.TextContent(type="text", text=f"Документація не знайдена: {mp}")]

    elif name == "save_knowledge":
        os.makedirs(f"{DATA_DIR}/knowledge", exist_ok=True)
        path = f"{DATA_DIR}/knowledge/{arguments['filename']}"
        with open(path, "w") as f:
            f.write(arguments["content"])
        return [types.TextContent(type="text", text=f"Збережено: {path}")]

    elif name == "read_knowledge":
        path = f"{DATA_DIR}/knowledge/{arguments['filename']}"
        if os.path.exists(path):
            with open(path) as f:
                return [types.TextContent(type="text", text=f.read())]
        return [types.TextContent(type="text", text="Файл не знайдено")]

    return [types.TextContent(type="text", text=f"Unknown: {name}")]

async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
