import { ArrowRight } from "lucide-react";
import type { RefObject } from "react";
import { AsOfDatePicker } from "../AsOfDatePicker";
import type { ScenarioDraftMode } from "../holdings";
import type { AccessResponse, SampleScenario } from "../types";

export function ScenarioPanel({
  access,
  scenarios,
  scenarioKey,
  scenarioDraftMode,
  onSelectScenario,
  onSetCustomMode,
  scenarioText,
  setScenarioText,
  selectedScenario,
  isRunning,
  onRun,
  asOfDate,
  setAsOfDate,
  latestClose,
  textareaRef
}: {
  access: AccessResponse | null;
  scenarios: SampleScenario[];
  scenarioKey: string;
  scenarioDraftMode: ScenarioDraftMode;
  onSelectScenario: (key: string) => void;
  onSetCustomMode: () => void;
  scenarioText: string;
  setScenarioText: (text: string) => void;
  selectedScenario?: SampleScenario;
  isRunning: boolean;
  onRun: () => void;
  asOfDate: string;
  setAsOfDate: (v: string) => void;
  latestClose: string;
  // Forwarded so App can focus the composer after an "Edit & re-run" hydration.
  textareaRef?: RefObject<HTMLTextAreaElement>;
}) {
  const isAdmin = access?.access_mode === "admin";
  const canEditText = Boolean(access);
  const chipScenarios = scenarios;
  const seededFrom =
    scenarioDraftMode === "custom" && selectedScenario ? selectedScenario.name : null;
  const runDisabled = isRunning || !scenarioText.trim();
  return (
    <section className="scenario-card">
      <div>
        <p className="eyebrow">Scenario</p>
        <h3>{isAdmin ? "Author or seed a stress narrative" : "Explore a stress narrative"}</h3>
      </div>
      {chipScenarios.length ? (
        <div className="scenario-chips" role="group" aria-label="Example scenarios">
          {chipScenarios.map((scenario) => (
            <button
              key={scenario.key}
              type="button"
              className={`chip${
                scenarioDraftMode === "sample" && scenario.key === scenarioKey ? " active" : ""
              }`}
              onClick={() => onSelectScenario(scenario.key)}
              title={scenario.text}
            >
              {scenario.name}
            </button>
          ))}
          <button
            type="button"
            className={`chip${scenarioDraftMode === "custom" ? " active" : ""}`}
            onClick={onSetCustomMode}
          >
            Custom
          </button>
        </div>
      ) : null}
      <div className="scenario-grid visitor-scenario-grid">
        <label className="scenario-text">
          Scenario text {seededFrom ? <span className="field-note">Seeded from {seededFrom}</span> : null}
          <textarea
            ref={textareaRef}
            className="scenario-text-input"
            value={scenarioText}
            onChange={(event) => setScenarioText(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !runDisabled) {
                event.preventDefault();
                onRun();
              }
            }}
            enterKeyHint="go"
            disabled={!canEditText}
            placeholder="Describe a market shock in plain English."
          />
        </label>
      </div>
      <div className="scenario-controls">
        {isAdmin ? (
          <AsOfDatePicker
            value={asOfDate}
            latestClose={latestClose}
            onChange={setAsOfDate}
            disabled={isRunning}
          />
        ) : null}
        <button className="primary-button" onClick={onRun} disabled={runDisabled}>
          {isRunning ? "Running pipeline..." : "Run hypothetical stress"}{" "}
          <ArrowRight size={16} />
        </button>
      </div>
    </section>
  );
}
