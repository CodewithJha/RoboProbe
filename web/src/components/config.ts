/** Shared component layout/virtualisation settings (T-086a/b; docs/13 §6). */
import tokens from '../styles/tokens.json';

export interface ComponentConfig {
  readonly rowHeight: number;
  readonly spineTickHeight: number;
  readonly viewportRows: number;
  readonly overscan: number;
  readonly tableVirtualizationThreshold: number;
  readonly tooltipDelayMs: number;
}

const unit = Number.parseFloat(tokens.space['--space-unit']);
export const componentConfig: ComponentConfig = {
  rowHeight: unit * 10,
  spineTickHeight: Number.parseFloat(tokens.space['--space-6']),
  viewportRows: 12,
  overscan: 5,
  tableVirtualizationThreshold: 200,
  tooltipDelayMs: Number.parseFloat(tokens.motion['--motion-slow']),
};
