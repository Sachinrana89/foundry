AGENTS = {
    "smart-center": {
        "name": "Smart Center",
        "short_name": "Smart Center",
        "description": "Enterprise knowledge and smart-center information.",
        "accent": "blue",
        "icon": "✦",
        "home_class": "smart",
    },
    "google-aarambh": {
        "name": "Google Aarambh",
        "short_name": "Google Aarambh",
        "description": "Aarambh knowledge, initiatives and supporting material.",
        "accent": "red",
        "icon": "G",
        "home_class": "aarambh",
    },
    "google-capabilities": {
        "name": "TCS Google Capabilities",
        "short_name": "TCS Google Capabilities",
        "description": "Google Cloud capabilities, solutions and technical content.",
        "accent": "green",
        "icon": "◆",
        "home_class": "capabilities",
    },
    "coe-repository": {
        "name": "TCS Google COE Repository Agents",
        "short_name": "COE Repository",
        "description": "COE repository knowledge, reusable assets and technical references.",
        "accent": "purple",
        "icon": "COE",
        "home_class": "coe",
    },
    "case-studies": {
        "name": "Case Studies",
        "short_name": "Case Studies",
        "description": "Client case studies, success stories, industry examples and reusable experience.",
        "accent": "orange",
        "icon": "▣",
        "home_class": "case-studies",
    },
    "deal-repository-solutions": {
        "name": "Deal Repository / Solutions",
        "short_name": "Deal Repository / Solutions",
        "description": "Deal knowledge, solution assets, proposals, reusable offerings and solution references.",
        "accent": "teal",
        "icon": "◇",
        "home_class": "deal-repository",
    },
    "learning-talent-development": {
        "name": "Learning and Talent Development",
        "short_name": "Learning & Talent Development",
        "description": "Learning resources, capability development, talent programs and training material.",
        "accent": "indigo",
        "icon": "★",
        "home_class": "learning",
    },
}


def get_agent(agent_id: str):
    return AGENTS.get(agent_id)


def ensure_agent_directories(base_dir):
    for agent_id in AGENTS:
        (base_dir / agent_id).mkdir(parents=True, exist_ok=True)
