import { ArrowRight } from "lucide-react";
import type { RefObject } from "react";
import { AsOfDatePicker } from "../AsOfDatePicker";
import { ChoiceGroup } from "../ChoiceGroup";
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
  horizon = 21,
  setHorizon = () => {},
  severity = 1,
  setSeverity = () => {},
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
  horizon?: 5 | 21 | 63;
  setHorizon?: (value: 5 | 21 | 63) => void;
  severity?: 1 | 1.5 | 2;
  setSeverity?: (value: 1 | 1.5 | 2) => void;
  // Forwarded so App can focus the composer after an "Edit & re-run" hydration.
  textareaRef?: RefObject<HTMLTextAreaElement>;
}) {
  const isAdmin = access?.access_mode === "admin";
  const canEditText = Boolean(access);
  const chipScenarios = scenarios;
  const seededFrom =
    scenarioDraftMode === "custom" && selectedScenario ? selectedScenario.name : null;
  const runDisabled = isRunning || !scenarioText.trim();
  const customChoice = "__custom__";
  const scenarioChoice = scenarioDraftMode === "custom" ? customChoice : scenarioKey;
  return (
    <section className="scenario-card">
      <div>
        <p className="eyebrow">Scenario</p>
        <h2>{isAdmin ? "Author or seed a stress narrative" : "Explore a stress narrative"}</h2>
      </div>
      {chipScenarios.length ? (
        <div className="scenario-chips-wrap">
          <ChoiceGroup
            ariaLabel="Example scenarios"
            className="scenario-chips"
            optionClassName="chip"
            value={scenarioChoice}
            onChange={(choice) => {
              if (choice === customChoice) onSetCustomMode();
              else onSelectScenario(choice);
            }}
            options={[
              ...chipScenarios.map((scenario) => ({
                key: scenario.key,
                label: scenario.name,
                title: scenario.text
              })),
              { key: customChoice, label: "Custom" }
            ]}
          />
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
        {access?.engine_mode === "quant_v2" ? (
          <div className="quant-run-controls" aria-label="Quant model controls">
            <label>
              Horizon
              <select
                value={horizon}
                onChange={(event) => setHorizon(Number(event.target.value) as 5 | 21 | 63)}
                disabled={isRunning}
              >
                <option value={5}>5 trading days</option>
                <option value={21}>21 trading days</option>
                <option value={63}>63 trading days</option>
              </select>
            </label>
            <label>
              Severity
              <select
                value={severity}
                onChange={(event) => setSeverity(Number(event.target.value) as 1 | 1.5 | 2)}
                disabled={isRunning}
              >
                <option value={1}>1× historical move</option>
                <option value={1.5}>1.5× historical move</option>
                <option value={2}>2× historical move</option>
              </select>
            </label>
          </div>
        ) : null}
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
