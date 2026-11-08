"""Genera las tarjetas de estadísticas del perfil (stats.svg y top-langs.svg).

Sustituye a github-readme-stats.vercel.app, cuya instancia pública dejó de
funcionar. Usa solo la API REST de GitHub y la biblioteca estándar.

Uso:  python generate.py <usuario> <carpeta_salida>
Variable opcional GITHUB_TOKEN para no topar con el límite de peticiones.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from html import escape

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Mismos colores que el resto del perfil
BG = "#0d1117"
ACCENT = "#00FF41"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
TRACK = "#1b2a1f"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"

# Colores de lenguaje (los de GitHub Linguist para los más habituales)
LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572A5",
    "PHP": "#4F5D95", "Java": "#b07219", "HTML": "#e34c26", "CSS": "#663399",
    "SCSS": "#c6538c", "Sass": "#a53b70", "Vue": "#41b883", "Shell": "#89e051",
    "Jupyter Notebook": "#DA5B0B", "C#": "#178600", "C++": "#f34b7d",
    "C": "#555555", "Go": "#00ADD8", "Rust": "#dea584", "Kotlin": "#A97BFF",
    "Dockerfile": "#384d54", "PLpgSQL": "#336790", "TSQL": "#e38c00",
    "Blade": "#f7523f", "PowerShell": "#012456", "Batchfile": "#C1F12E", "Astro": "#ff5a03", "Svelte": "#ff3e00",
}
# Lenguajes que no aportan nada a la tarjeta
IGNORED_LANGS = {"Jupyter Notebook"}


def get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def owned_repos(user):
    repos, page = [], 1
    while True:
        batch = get(f"/users/{user}/repos",
                    {"type": "owner", "per_page": 100, "page": page})
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


def search_count(kind, query):
    return get(f"/search/{kind}", {"q": query, "per_page": 1})["total_count"]


def collect(user):
    profile = get(f"/users/{user}")
    repos = [r for r in owned_repos(user) if not r["fork"]]

    langs = {}
    for r in repos:
        if r["name"].lower() == user.lower():  # el propio repo del perfil
            continue
        for lang, size in get(f"/repos/{r['full_name']}/languages").items():
            if lang not in IGNORED_LANGS:
                langs[lang] = langs.get(lang, 0) + size

    return {
        "name": profile.get("name") or user,
        "stars": sum(r["stargazers_count"] for r in repos),
        "commits": search_count("commits", f"author:{user}"),
        "repos": len(repos),
        "followers": profile.get("followers", 0),
        "langs": langs,
    }


def fmt(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <title>{escape(title)}</title>
  <style>
    .t {{ font: 600 18px {FONT}; fill: {ACCENT}; }}
    .l {{ font: 600 14px {FONT}; fill: {TEXT}; }}
    .v {{ font: 700 14px {FONT}; fill: {TEXT}; }}
    .s {{ font: 400 11px {FONT}; fill: {MUTED}; }}
    .big {{ font: 800 26px {FONT}; fill: {ACCENT}; }}
    .in {{ opacity: 0; animation: in .5s ease-out forwards; }}
    @keyframes in {{ to {{ opacity: 1; }} }}
    @keyframes ring {{ from {{ stroke-dashoffset: 251.3; }} }}
  </style>
  <rect width="{width}" height="{height}" rx="6" fill="{BG}"/>
  <text x="25" y="35" class="t">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(d):
    rows = [
        ("Estrellas", d["stars"]),
        ("Commits", d["commits"]),
        ("Repositorios", d["repos"]),
        ("Lenguajes", len(d["langs"])),
        ("Seguidores", d["followers"]),
    ]
    body = []
    for i, (label, value) in enumerate(rows):
        y = 70 + i * 25
        body.append(
            f'  <g class="in" style="animation-delay:{150 + i * 120}ms">'
            f'<circle cx="31" cy="{y - 5}" r="4" fill="{ACCENT}"/>'
            f'<text x="45" y="{y}" class="l">{label}:</text>'
            f'<text x="200" y="{y}" class="v">{fmt(value)}</text></g>')

    # Anillo: commits frente a una meta redonda (siguiente centena)
    goal = max(100, -(-d["commits"] // 100) * 100)
    filled = 251.3 * (1 - d["commits"] / goal)
    body.append(f"""  <g transform="translate(372 100)">
    <circle r="40" fill="none" stroke="{TRACK}" stroke-width="6"/>
    <circle r="40" fill="none" stroke="{ACCENT}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="251.3" stroke-dashoffset="{filled:.1f}" transform="rotate(-90)"
      style="animation: ring 1s ease-out"/>
    <text y="6" text-anchor="middle" class="big">{fmt(d['commits'])}</text>
    <text y="62" text-anchor="middle" class="s">commits</text>
  </g>""")
    return card(467, 195, f"Estadísticas de {d['name']}", "\n".join(body))


def langs_svg(d, top=6):
    ranked = sorted(d["langs"].items(), key=lambda kv: kv[1], reverse=True)[:top]
    total = sum(v for _, v in ranked) or 1
    width, bar_w = 300, 250

    body, x = [], 25.0
    body.append(f'  <clipPath id="bar"><rect x="25" y="55" width="{bar_w}" height="8" rx="4"/></clipPath>')
    body.append('  <g clip-path="url(#bar)">')
    for lang, size in ranked:
        w = bar_w * size / total
        body.append(f'    <rect x="{x:.2f}" y="55" width="{w + 0.5:.2f}" height="8" '
                    f'fill="{LANG_COLORS.get(lang, MUTED)}"/>')
        x += w
    body.append("  </g>")

    for i, (lang, size) in enumerate(ranked):
        col, row = i % 2, i // 2
        cx, cy = 25 + col * 135, 92 + row * 34
        body.append(
            f'  <g class="in" style="animation-delay:{150 + i * 100}ms">'
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{LANG_COLORS.get(lang, MUTED)}"/>'
            f'<text x="{cx + 16}" y="{cy}" class="l" style="font-size:12px">{escape(lang)}</text>'
            f'<text x="{cx + 16}" y="{cy + 13}" class="s">{100 * size / total:.1f}%</text></g>')

    height = 92 + ((len(ranked) + 1) // 2) * 34 - 5
    return card(width, max(height, 165), "Lenguajes más usados", "\n".join(body))


def main():
    user, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    data = collect(user)
    with open(os.path.join(out, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg(data))
    with open(os.path.join(out, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg(data))
    print(json.dumps({k: v for k, v in data.items() if k != "langs"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
