/** Runtime views of document-defined parameters and plugin metadata (T-087b). */
import { Validator, type Schema as JsonSchema } from '@cfworker/json-schema';
import type { Schema } from '../../../api/client';
import campaignSchema from '../../../../../schemas/campaign.schema.json';
import { stringify } from 'yaml';

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type CampaignRequest = Schema['CampaignCreate'];
export interface Backend {
  id: string;
  description: string;
  typicalSeconds?: number;
}
export interface Strategy {
  id: string;
  description: string;
  schema: Record<string, unknown>;
}
export function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
export function backends(meta: unknown): Backend[] {
  const list = object(meta)['backends'];
  if (!Array.isArray(list)) return [];
  return list.flatMap((raw) => {
    const item = object(raw);
    const id = text(item['id']) || text(item['name']);
    const caps = object(item['capabilities']);
    const seconds = caps['typical_episode_wall_s'];
    return id
      ? [
          {
            id,
            description: text(item['description']),
            ...(typeof seconds === 'number' ? { typicalSeconds: seconds } : {}),
          },
        ]
      : [];
  });
}
export function strategies(meta: unknown): Strategy[] {
  const list = object(meta)['strategies'];
  if (!Array.isArray(list)) return [];
  return list.flatMap((raw) => {
    const item = object(raw);
    const id = text(item['id']) || text(item['name']);
    return id
      ? [
          {
            id,
            description: text(item['description']) || id,
            schema: object(item['params_schema']),
          },
        ]
      : [];
  });
}
// Strategy schemas arrive at runtime. Interpret them under the production CSP.
const validateCampaign = new Validator(campaignSchema as JsonSchema, '2020-12', false);
function validationErrors(validator: Validator, data: unknown, prefix = '') {
  return validator
    .validate(data)
    .errors.filter((error) => error.keyword !== 'properties')
    .map((error) => ({
      pointer: `${prefix}${error.instanceLocation.replace(/^#/, '')}`,
      detail: error.error,
    }));
}

export function validateRequest(
  payload: CampaignRequest,
  strategy?: Strategy,
): { pointer: string; detail: string }[] {
  const errors = validationErrors(validateCampaign, payload);
  if (strategy && Object.keys(strategy.schema).length) {
    try {
      const validator = new Validator(strategy.schema, '2020-12', false);
      errors.push(
        ...validationErrors(validator, payload.strategy.params ?? {}, '/strategy/params'),
      );
    } catch {
      errors.push({
        pointer: '/strategy/params',
        detail: 'The server supplied an unsupported strategy schema.',
      });
    }
  }
  return errors;
}
export function toYaml(payload: CampaignRequest): string {
  return stringify({ schema_version: 1, ...payload }, { sortMapEntries: true });
}
export function errorStep(pointer: string): number {
  const path = pointer.replace(/^\/body/, '');
  if (/^\/(space|pins)(\/|$)/.test(path)) return 0;
  if (/^\/(backend|sut_profile_id|repeats)(\/|$)/.test(path)) return 1;
  if (/^\/(strategy|budget|batch_size)(\/|$)/.test(path)) return 2;
  return 3;
}
