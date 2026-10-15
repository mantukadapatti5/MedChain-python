import { useEffect, useMemo, useState } from "react";
import { Brain, Database, Target, CheckCircle2, XCircle, Layers } from "lucide-react";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";
import ModelNotice from "../../components/ModelNotice";
import LineChartSVG from "../../components/LineChartSVG";

const MODEL_COLORS = {
  actual: "#0f172a",
  rf: "#2563eb",
  xgboost: "#16a34a",
  lstm: "#ea580c",
  ensemble: "#7c3aed",
};

const MODEL_LABELS = { rf: "Random Forest", xgboost: "XGBoost", lstm: "LSTM", ensemble: "Ensemble" };

export default function VendorAnalytics() {
  const [catalog, setCatalog] = useState(null);
  const [drugId, setDrugId] = useState(null);
  const [region, setRegion] = useState(null);
  const [days, setDays] = useState(7);
  const [forecast, setForecast] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/vendor/demand-forecast-v2/catalog")
      .then((c) => {
        setCatalog(c);
        if (c.drugs.length) { setDrugId(c.drugs[0].Drug_ID); setRegion(c.regions[0]); }
      })
      .catch((e) => setError(e.message));
    api.get("/vendor/demand-forecast-v2/model-info").then(setModelInfo).catch(() => {});
  }, []);

  useEffect(() => {
    if (!drugId || !region) return;
    setLoading(true);
    api.get(`/vendor/demand-forecast-v2?drugId=${drugId}&region=${region}&days=${days}`)
      .then((r) => { setForecast(r); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [drugId, region, days]);

  const chartData = useMemo(() => {
    if (!forecast) return null;
    const xLabels = [...forecast.history.map((h) => h.date), ...forecast.forecastDates];
    const splitIndex = forecast.history.length - 1;

    const actualPoints = [
      ...forecast.history.map((h) => ({ y: h.actual })),
      ...forecast.forecastDates.map(() => ({ y: null })),
    ];
    const seriesFor = (key) => {
      const vals = forecast.forecast[key];
      if (!vals) return null;
      return {
        key, label: MODEL_LABELS[key], color: MODEL_COLORS[key],
        emphasize: key === "ensemble", dashed: key !== "ensemble",
        points: [
          ...forecast.history.map(() => ({ y: null })),
          ...vals.map((v) => ({ y: v })),
        ],
      };
    };

    const series = [
      { key: "actual", label: "Actual (history)", color: MODEL_COLORS.actual, emphasize: true, points: actualPoints },
      seriesFor("rf"), seriesFor("xgboost"), seriesFor("lstm"), seriesFor("ensemble"),
    ].filter(Boolean);

    return { xLabels, series, splitIndex };
  }, [forecast]);

  if (error) return <ErrorBanner message={error} />;
  if (!catalog) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Brain size={18} className="text-vendor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Demand Forecasting &amp; Analytics</h2>
          <p className="text-sm text-slate-500">
            Random Forest demand model trained on 182K synthetic consumption records
            (Jan 2022 – Jun 2024) across 20 drugs and 10 regions. The LSTM and XGBoost models in the
            pipeline design are not trained in this build.
          </p>
        </div>
      </div>

      <ModelNotice kind="forecast" />

      {/* Architecture strip (pipeline design; only the Random Forest is trained here) */}
      <div className="card p-4 flex items-center justify-center gap-3 text-xs text-slate-500 bg-gradient-to-r from-vendor-soft to-white overflow-x-auto">
        <span className="badge bg-slate-100 border border-slate-200">CSV Dataset</span>
        <span>→</span>
        <span className="badge" style={{ color: MODEL_COLORS.lstm, background: "#fff7ed", border: "1px solid #fed7aa" }}>LSTM</span>
        <span>+</span>
        <span className="badge" style={{ color: MODEL_COLORS.rf, background: "#eff6ff", border: "1px solid #bfdbfe" }}>Random Forest</span>
        <span>+</span>
        <span className="badge" style={{ color: MODEL_COLORS.xgboost, background: "#f0fdf4", border: "1px solid #bbf7d0" }}>XGBoost</span>
        <span>→</span>
        <span className="badge" style={{ color: MODEL_COLORS.ensemble, background: "#f5f3ff", border: "1px solid #ddd6fe" }}>Ensemble</span>
        <span>→</span>
        <span className="badge bg-slate-100 border border-slate-200">Forecast</span>
      </div>

      {/* Model status */}
      {modelInfo && (
        <div className="card p-5">
          <div className="flex items-center gap-1.5 mb-3">
            <Database size={15} className="text-vendor" />
            <p className="font-semibold text-ink-900 text-sm">Model Training Report</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {["rf", "xgboost", "lstm"].map((key) => {
              const m = modelInfo[key];
              const trained = m?.status === "trained";
              return (
                <div key={key} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold text-sm" style={{ color: MODEL_COLORS[key] }}>{MODEL_LABELS[key]}</p>
                    {trained ? (
                      <span className="badge bg-emerald-50 text-emerald-700 border border-emerald-200"><CheckCircle2 size={11} /> Trained</span>
                    ) : (
                      <span className="badge bg-slate-100 text-slate-500 border border-slate-200"><XCircle size={11} /> Not trained</span>
                    )}
                  </div>
                  {trained && m.test_metrics && (
                    <div className="mt-2 text-[11px] text-slate-500 space-y-0.5">
                      <p className="flex items-center gap-1"><Target size={10} /> R&sup2; = {m.test_metrics.r2}</p>
                      <p>MAE = {m.test_metrics.mae} &middot; MAPE = {m.test_metrics.mape}%</p>
                    </div>
                  )}
                  {!trained && (
                    <p className="mt-2 text-[11px] text-slate-400">
                      Run <code>python -m app.ml.demand.train_{key}</code> (requires <code>requirements-ml.txt</code>)
                    </p>
                  )}
                </div>
              );
            })}
          </div>
          {modelInfo.ensemble_weights && Object.keys(modelInfo.ensemble_weights).length > 0 && (
            <p className="text-[11px] text-slate-500 mt-3 flex items-center gap-1">
              <Layers size={11} /> Ensemble weights (from validation MAE):{" "}
              {Object.entries(modelInfo.ensemble_weights).map(([k, v]) => `${MODEL_LABELS[k]} ${(v * 100).toFixed(0)}%`).join(" · ")}
            </p>
          )}
        </div>
      )}

      {/* Selectors */}
      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div>
          <label className="text-[11px] uppercase text-slate-400 block mb-1">Drug</label>
          <select className="input" value={drugId || ""} onChange={(e) => setDrugId(e.target.value)}>
            {catalog.drugs.map((d) => <option key={d.Drug_ID} value={d.Drug_ID}>{d.Drug_Name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] uppercase text-slate-400 block mb-1">Region</label>
          <select className="input" value={region || ""} onChange={(e) => setRegion(e.target.value)}>
            {catalog.regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[11px] uppercase text-slate-400 block mb-1">Forecast horizon</label>
          <select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Next 7 days</option>
            <option value={14}>Next 14 days</option>
            <option value={30}>Next 30 days</option>
          </select>
        </div>
      </div>

      {/* Chart */}
      <div className="card p-5">
        {loading || !chartData ? (
          <div className="h-64 rounded-xl bg-slate-100 animate-pulse" />
        ) : (
          <>
            <div className="flex items-center justify-between mb-2">
              <p className="font-semibold text-ink-900">{forecast.drugName} — {forecast.region}</p>
              <p className="text-sm text-vendor font-semibold">
                Forecast total (next {days}d): {forecast.forecastTotalNextPeriod} units
              </p>
            </div>
            <LineChartSVG series={chartData.series} xLabels={chartData.xLabels} splitIndex={chartData.splitIndex} />
          </>
        )}
      </div>

      {/* Per-model comparison table */}
      {forecast && (
        <div className="card p-5 overflow-x-auto">
          <p className="font-semibold text-ink-900 text-sm mb-3">Day-by-day model comparison</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 uppercase text-[10px]">
                <th className="py-1 pr-4">Date</th>
                <th className="py-1 pr-4">Random Forest</th>
                <th className="py-1 pr-4">XGBoost</th>
                <th className="py-1 pr-4">LSTM</th>
                <th className="py-1 pr-4">Ensemble</th>
              </tr>
            </thead>
            <tbody>
              {forecast.forecastDates.map((date, i) => (
                <tr key={date} className="border-t border-slate-100">
                  <td className="py-1.5 pr-4 text-slate-500">{date}</td>
                  <td className="py-1.5 pr-4">{forecast.forecast.rf?.[i] ?? "—"}</td>
                  <td className="py-1.5 pr-4">{forecast.forecast.xgboost?.[i] ?? "—"}</td>
                  <td className="py-1.5 pr-4">{forecast.forecast.lstm?.[i] ?? "—"}</td>
                  <td className="py-1.5 pr-4 font-semibold text-vendor">{forecast.forecast.ensemble?.[i] ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
