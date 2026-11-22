import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { Campaign } from '../../../api/hooks';
import { AppProviders } from '../../../app/providers';
import { CampaignHeader } from './CampaignHeader';

const running: Campaign = {
  id: 'c1',
  status: 'RUNNING',
  name: 'Night shift',
  strategy: { id: 'S-PROBE', seed: 42 },
  backend: 'kinematic2d',
  budget: 20,
  batch_size: 1,
  repeats: 1,
  modes_found: 0,
};

it('wraps cancellation dialog focus at both keyboard boundaries', () => {
  render(
    <AppProviders live={false}>
      <CampaignHeader campaign={running} />
    </AppProviders>,
  );
  const dialog = screen.getByLabelText('Cancel campaign confirmation');
  dialog.setAttribute('open', '');
  const keep = within(dialog).getByRole('button', { name: 'Keep campaign' });
  const confirm = within(dialog).getByRole('button', { name: 'Confirm cancellation' });

  confirm.focus();
  expect(fireEvent.keyDown(confirm, { key: 'Tab' })).toBe(false);
  expect(keep).toHaveFocus();

  expect(fireEvent.keyDown(keep, { key: 'Tab', shiftKey: true })).toBe(false);
  expect(confirm).toHaveFocus();
});
