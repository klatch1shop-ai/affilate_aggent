import os
import glob

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "../../shared/skills")

def list_skills(agent_name: str = None) -> list:
    """Список доступних скілів для агента"""
    if agent_name:
        pattern = os.path.join(SKILLS_DIR, agent_name, "*.md")
    else:
        pattern = os.path.join(SKILLS_DIR, "**/*.md")
    
    skills = []
    for path in glob.glob(pattern, recursive=True):
        with open(path) as f:
            first_line = f.readline().strip().lstrip("# ")
        skills.append({
            "name": os.path.basename(path).replace(".md",""),
            "path": path,
            "description": first_line,
            "agent": path.split("/")[-2]
        })
    return skills

def load_skill(agent_name: str, skill_name: str) -> str:
    """Завантажити конкретний скіл"""
    path = os.path.join(SKILLS_DIR, agent_name, f"{skill_name}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""

def get_skills_context(agent_name: str) -> str:
    """Отримати контекст скілів для агента"""
    skills = list_skills(agent_name)
    if not skills:
        return ""
    lines = [f"\nДоступні скіли для {agent_name}:"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    return "\n".join(lines)

def load_all_skills(agent_name: str) -> str:
    """Завантажити всі скіли агента в один текст"""
    skills = list_skills(agent_name)
    if not skills:
        return ""
    parts = []
    for s in skills:
        with open(s["path"]) as f:
            parts.append(f.read())
    return "\n\n---\n\n".join(parts)
