import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface ChoiceOption<K extends string> {
  key: K;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

interface ChoiceGroupProps<K extends string> {
  ariaLabel: string;
  value: K;
  options: readonly ChoiceOption<K>[];
  onChange: (key: K) => void;
  className?: string;
  optionClassName?: string | ((option: ChoiceOption<K>) => string | undefined);
}

/** Single-choice control with automatic activation and one keyboard tab stop. */
export function ChoiceGroup<K extends string>({
  ariaLabel,
  value,
  options,
  onChange,
  className,
  optionClassName
}: ChoiceGroupProps<K>) {
  const optionRefs = useRef(new Map<K, HTMLButtonElement>());
  const enabled = options.filter((option) => !option.disabled);
  const selected = options.find((option) => option.key === value && !option.disabled);
  const tabStopKey = selected?.key ?? enabled[0]?.key;

  function selectAndFocus(key: K) {
    optionRefs.current.get(key)?.focus();
    if (key !== value) onChange(key);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!enabled.length) return;
    const currentIndex = enabled.findIndex((option) => option.key === value);
    let next: ChoiceOption<K> | undefined;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = enabled[(currentIndex + 1) % enabled.length];
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      const previousIndex =
        currentIndex < 0 ? enabled.length - 1 : (currentIndex - 1 + enabled.length) % enabled.length;
      next = enabled[previousIndex];
    } else if (event.key === "Home") {
      next = enabled[0];
    } else if (event.key === "End") {
      next = enabled[enabled.length - 1];
    }

    if (!next) return;
    event.preventDefault();
    selectAndFocus(next.key);
  }

  return (
    <div className={className} role="radiogroup" aria-label={ariaLabel} onKeyDown={onKeyDown}>
      {options.map((option) => {
        const baseClass =
          typeof optionClassName === "function" ? optionClassName(option) : optionClassName;
        const classes = [baseClass, option.key === value ? "active" : null]
          .filter(Boolean)
          .join(" ");
        return (
          <button
            key={option.key}
            ref={(node) => {
              if (node) optionRefs.current.set(option.key, node);
              else optionRefs.current.delete(option.key);
            }}
            type="button"
            role="radio"
            aria-checked={option.key === value}
            tabIndex={option.key === tabStopKey ? 0 : -1}
            className={classes || undefined}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.key)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
