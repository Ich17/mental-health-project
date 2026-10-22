import { useEffect, useState } from "react";

// Squelette : vérifie que le front parle bien à l'API. Les vrais écrans (CLAUDE.md §10) viennent ensuite.
export default function App() {
  const [health, setHealth] = useState(null);
  const [forecast, setForecast] = useState([]);

  useEffect(() => {
    fetch("/health").then((r) => r.json()).then(setHealth).catch(() => setHealth({ status: "injoignable" }));
    fetch("/api/forecast").then((r) => r.json()).then(setForecast).catch(() => {});
  }, []);

  const color = { vert: "bg-emerald-100 text-emerald-800", orange: "bg-amber-100 text-amber-800", rouge: "bg-rose-100 text-rose-800" };

  return (
    <main className="mx-auto max-w-2xl p-6 font-sans text-slate-800">
      <h1 className="text-2xl font-semibold">Mental Health Project</h1>
      <p className="mt-1 text-sm text-slate-500">
        API : {health ? `${health.status} · Postgres ${health.postgres ?? "?"}` : "…"}
      </p>
      <h2 className="mt-8 text-lg font-medium">Ma semaine prochaine (mock)</h2>
      <ul className="mt-3 space-y-2">
        {forecast.map((d) => (
          <li key={d.date} className={`flex justify-between rounded-lg px-4 py-3 ${color[d.risk] ?? ""}`}>
            <span>{d.date}</span>
            <span>récupération prévue {d.predicted_recovery} · {d.reason}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
