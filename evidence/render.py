"""Page HTML du rapport avant / après (autonome, une seule page). Appelé par evidence.before_after."""

HEAD = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Baseline · Preuve avant/après</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>
/* une colonne de lecture, chiffres clés en tête, deux parties nettes : réel puis simulé */
:root{--bg:#f6f7f4;--fg:#1d2420;--mute:#5d6862;--line:#d9ded8;--card:#fff;--red:#c2453a;--green:#2f7d5b;--accent:#2f5d7d;--disp:'Fraunces',Georgia,serif;--body:'IBM Plex Sans',system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131715;--fg:#e8ece9;--mute:#9aa59f;--line:#2b322e;--card:#1b201d;--red:#e0675c;--green:#55b68a;--accent:#7fb0d4;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#131715;--fg:#e8ece9;--mute:#9aa59f;--line:#2b322e;--card:#1b201d;--red:#e0675c;--green:#55b68a;--accent:#7fb0d4;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--body);font-size:15px;line-height:1.55}
main{max-width:860px;margin:0 auto;padding-block:32px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:28px}
h1,h2{font-family:var(--disp);text-wrap:balance;margin:0} h1{font-size:2.1rem} h2{font-size:1.35rem}
.eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;color:var(--mute);font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi b{font-family:var(--disp);font-size:2rem;display:block;font-variant-numeric:tabular-nums}
.kpi span{color:var(--mute);font-size:.88rem}
.tag{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid currentColor}
.real{color:var(--green)} .sim{color:var(--accent)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums} td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;font-size:.9rem} th{color:var(--mute);font-weight:600}
.wrap{overflow-x:auto} .bar{height:7px;background:var(--line);border-radius:4px;margin:3px 0;min-width:90px} .bar i{display:block;height:100%;border-radius:4px} .r{background:var(--red)} .g{background:var(--green)}
p{margin:0;max-width:68ch} section{display:grid;gap:12px} ul{margin:0;padding-left:20px;max-width:68ch} .note{color:var(--mute);font-size:.85rem}
</style>
"""


def pct(x):
    return f"{x:.0%}"


def render(r: dict) -> str:
    bt, c = r["backtest"], r["cohort"]
    s = c["scenarios"]
    top = max([1] + [t["after_real"]["red_days"] for t in r["teams"]])
    rows = ""
    for t in r["teams"]:
        a, b = t["after_real"]["red_days"], t["after_agent"]["red_days"]
        rows += (f"<tr><td>{t['team'].replace('_', ' ')}</td><td>{t['n_bucket']}</td><td>{t['after_real']['avg']:.0f}</td>"
                 f"<td>{t['after_agent']['avg']:.0f}</td><td><div class=bar><i style='width:{a / top * 100:.0f}%' class=r></i></div>"
                 f"<div class=bar><i style='width:{b / top * 100:.0f}%' class=g></i></div></td><td>{(b - a) / max(1, a):+.0%}</td></tr>")
    source = ("cohorte de démonstration de 40 profils calés sur des données Whoop réelles." if r["demo"] else
              "Whoop réel pour Ichane, 39 profils de démonstration calés sur ses moyennes.")
    gain = (s["central"]["red_days"] - c["after_real"]["red_days"]) / max(1, c["after_real"]["red_days"])
    fewer_fa = (bt["body_only"]["false_alarms"] - bt["all"]["false_alarms"]) / max(1, bt["body_only"]["false_alarms"])
    return HEAD + f"""<main>
<header style="display:grid;gap:8px"><div class=eyebrow>Baseline · Hackathon Accel × Aiven · {r['period']['start']} → {r['period']['after_end']}</div>
<h1>On voit venir les jours rouges, la veille</h1>
<p>{r['n_people']} salariés, {r['n_teams']} équipes, 50 jours. Jours 1 à 25 : aucun outil, les journées difficiles arrivent sans prévenir. Jours 26 à 50 : Baseline signale le risque le matin et allège l'agenda.</p></header>
<div class=kpis>
<div class=kpi><b>{pct(bt['all']['recall'])}</b><span>des jours de récupération rouge signalés la veille au matin <span class="tag real">backtest</span></span></div>
<div class=kpi><b>0 %</b><span>signalés aujourd'hui : ni la montre ni l'agenda ne préviennent</span></div>
<div class=kpi><b>{gain:+.0%}</b><span>de jours rouges quand l'agent agit en amont <span class="tag sim">projection</span></span></div>
<div class=kpi><b>{fewer_fa:.0%}</b><span>de fausses alertes en moins en croisant corps × agenda</span></div>
</div>
<section><div><span class="tag real">Partie 1 · mesuré</span></div><h2>Avant : les jours rouges que personne n'a vus venir</h2>
<p>Chaque matin, le modèle ne voit que le passé : récupération, HRV et sommeil du jour, plus les réunions déjà posées dans l'agenda. Il estime le risque que la récupération du lendemain passe sous {r['red']} % (zone rouge Whoop). Aucune donnée future n'est utilisée.</p>
<div class=wrap><table><tr><th></th><th>Jours 12-25</th><th>Jours 12-50</th><th>Corps seul (montre)</th></tr>
<tr><td>Jours rouges réels</td><td>{bt['before']['reds']}</td><td>{bt['all']['reds']}</td><td>{bt['body_only']['reds']}</td></tr>
<tr><td>Signalés la veille</td><td>{bt['before']['caught']} ({pct(bt['before']['recall'])})</td><td>{bt['all']['caught']} ({pct(bt['all']['recall'])})</td><td>{bt['body_only']['caught']} ({pct(bt['body_only']['recall'])})</td></tr>
<tr><td>Alertes justes</td><td>{pct(bt['before']['precision'])}</td><td>{pct(bt['all']['precision'])}</td><td>{pct(bt['body_only']['precision'])}</td></tr>
<tr><td>Fausses alertes</td><td>{bt['before']['false_alarms']}</td><td>{bt['all']['false_alarms']}</td><td>{bt['body_only']['false_alarms']}</td></tr></table></div>
<p class=note>Jours 1-11 : calibrage (modèle commun, puis personnel dès 10 jours d'historique). Lien heures de réunion (J) ↔ récupération (J+1) : corrélation {r['corr']:+.2f}.</p></section>
<section><div><span class="tag sim">Partie 2 · projection</span></div><h2>Après : l'agent agit la veille, les jours rouges reculent</h2>
<p>Mêmes personnes, mêmes jours 26 à 50. On compare la récupération réelle à celle qu'on obtient si, sur chaque jour signalé, l'agent propose de déplacer jusqu'à {r['hyp']['max_cut_h']:.0f} h de réunions et de bloquer un créneau « Occupé ».</p>
<div class=wrap><table><tr><th>Équipe</th><th>Taille</th><th>Récup. réelle</th><th>Avec agent</th><th>Jours rouges <span class=note>(rouge réel, vert avec agent)</span></th><th>Écart</th></tr>{rows}</table></div>
<div class=wrap><table><tr><th>Scénario</th><th>Part causale du lien charge → récup</th><th>Jours rouges</th><th>Récup. moyenne</th></tr>
<tr><td>Sans agent (réel)</td><td>-</td><td>{c['after_real']['red_days']}</td><td>{c['after_real']['avg']:.1f}</td></tr>
<tr><td>Prudent</td><td>25 %</td><td>{s['prudent']['red_days']}</td><td>{s['prudent']['avg']:.1f}</td></tr>
<tr><td><b>Central</b></td><td>50 %</td><td><b>{s['central']['red_days']}</b></td><td><b>{s['central']['avg']:.1f}</b></td></tr>
<tr><td>Optimiste</td><td>100 %</td><td>{s['optimiste']['red_days']}</td><td>{s['optimiste']['avg']:.1f}</td></tr></table></div>
<p class=note>Hypothèses : {r['hyp']['acceptance']:.0%} des propositions acceptées en 1 clic ; gain = pente perso « heures de réunion → récup du lendemain » mesurée sur les jours 1-25 seulement (moyenne {r['slope']:.1f} points par heure) × heures déplacées × part causale ; aucun effet compté les jours non signalés ni d'effet cumulé.</p></section>
<section><h2>Confidentialité</h2><ul>
<li>Métadonnées d'agenda et de mails uniquement, jamais de contenu.</li>
<li>Vue équipes : agrégats uniquement, équipes de moins de 8 personnes masquées.</li>
<li>On mesure la fatigue et la récupération, jamais les émotions.</li></ul>
<p class=note>Méthode : {source} Partie 2 = projection à partir des pentes mesurées en partie 1. Recalcul complet : <code>evidence/before_after.py</code>.</p></section>
</main>"""
