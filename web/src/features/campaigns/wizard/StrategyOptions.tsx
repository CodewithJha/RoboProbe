import { useState } from 'react';
import { type Json, object } from './model';

function Option({
  name,
  schema,
  value,
  change,
}: {
  name: string;
  schema: Record<string, unknown>;
  value: Json | undefined;
  change: (value: Json | undefined) => void;
}) {
  const [raw, setRaw] = useState<string>();
  const label = typeof schema['title'] === 'string' ? schema['title'] : name;
  const hint = typeof schema['description'] === 'string' ? schema['description'] : undefined;
  const initial = schema['default'];
  const choices = Array.isArray(schema['enum']) ? (schema['enum'] as Json[]) : undefined;
  const type =
    schema['type'] ??
    (Array.isArray(schema['anyOf']) ? object(schema['anyOf'][0])['type'] : undefined);
  const displayDefault =
    initial === undefined ? 'Use default' : `Default: ${JSON.stringify(initial)}`;
  return (
    <label>
      {label}
      {choices || type === 'boolean' ? (
        <select
          value={value === undefined ? '' : JSON.stringify(value)}
          onChange={(event) => {
            const selected = event.target.value;
            change(selected ? (JSON.parse(selected) as Json) : undefined);
          }}
        >
          <option value="">{displayDefault}</option>
          {(choices ?? [true, false]).map((choice) => (
            <option key={JSON.stringify(choice)} value={JSON.stringify(choice)}>
              {typeof choice === 'string' ? choice : JSON.stringify(choice)}
            </option>
          ))}
        </select>
      ) : type === 'number' || type === 'integer' || type === 'string' ? (
        <input
          type={type === 'string' ? 'text' : 'number'}
          step={type === 'integer' ? 1 : 'any'}
          min={typeof schema['minimum'] === 'number' ? schema['minimum'] : undefined}
          max={typeof schema['maximum'] === 'number' ? schema['maximum'] : undefined}
          placeholder={displayDefault}
          value={typeof value === 'string' || typeof value === 'number' ? value : ''}
          onChange={(event) => {
            const entered = event.target.value;
            change(
              entered === '' ? undefined : type === 'string' ? entered : event.target.valueAsNumber,
            );
          }}
        />
      ) : (
        <textarea
          placeholder={displayDefault}
          rows={3}
          value={raw ?? (value === undefined ? '' : JSON.stringify(value, null, 2))}
          onChange={(event) => {
            const entered = event.target.value;
            setRaw(entered);
            try {
              change(entered.trim() ? (JSON.parse(entered) as Json) : undefined);
            } catch {
              change(entered);
            }
          }}
        />
      )}
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

export function StrategyOptions({
  schema,
  values,
  onChange,
}: {
  schema: Record<string, unknown>;
  values: Record<string, Json>;
  onChange: (values: Record<string, Json>) => void;
}) {
  const fields = Object.entries(object(schema['properties']));
  return (
    <details>
      <summary>Advanced strategy parameters</summary>
      {fields.length ? (
        fields.map(([name, property]) => (
          <Option
            key={name}
            name={name}
            schema={object(property)}
            value={values[name]}
            change={(value) => {
              if (value === undefined)
                onChange(
                  Object.fromEntries(Object.entries(values).filter(([key]) => key !== name)),
                );
              else onChange({ ...values, [name]: value });
            }}
          />
        ))
      ) : (
        <p>This strategy has no configurable parameters.</p>
      )}
    </details>
  );
}
