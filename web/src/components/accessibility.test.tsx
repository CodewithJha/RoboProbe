import axe from 'axe-core';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import {
  ConditionStrip,
  EmptyState,
  RobustnessBar,
  Spine,
  SpecimenTag,
  StatTable,
  VerdictNotch,
} from './index';

it('has no axe violations across the shared components (NFR-ACC-001)', async () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  const { container } = render(
    <MemoryRouter>
      <main>
        <h1>Component accessibility</h1>
        <ConditionStrip values={[0.5]} labels={['Speed']} formatted={['0.3 m/s']} size="sm" />
        <SpecimenTag kind="run" id="87" label="Collision" verdict="FAIL" />
        <VerdictNotch verdict="PASS" />
        <RobustnessBar value={-0.37} />
        <Spine runs={[{ id: '87', ordinal: 87, verdict: 'FAIL' }]} onSelect={vi.fn()} />
        <EmptyState title="No cases yet" body="Failures will appear as the campaign runs." />
        <StatTable
          rows={[{ id: '87', count: 23 }]}
          columns={[
            { key: 'id', header: 'Run' },
            { key: 'count', header: 'Count', align: 'right' },
          ]}
          rowKey={(row) => row.id}
          caption="Runs"
        />
      </main>
    </MemoryRouter>,
  );
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
  expect(result.violations).toEqual([]);
});
