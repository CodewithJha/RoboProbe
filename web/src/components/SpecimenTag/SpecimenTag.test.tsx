import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SpecimenTag } from './SpecimenTag';

describe('SpecimenTag', () => {
  it('links to an encoded run id and names its verdict', () => {
    render(
      <MemoryRouter>
        <SpecimenTag kind="run" id="run 87" verdict="FAIL" label="Collision" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'run 87 Collision, Run, FAIL' })).toHaveAttribute(
      'href',
      '/runs/run%2087',
    );
  });
  it('supports a campaign-scoped mode route and separate strip control', () => {
    render(
      <MemoryRouter>
        <SpecimenTag
          kind="mode"
          id="FM-03"
          verdict="FAIL"
          label="Dark-fast-noisy"
          to="/campaigns/c/casebook?mode=FM-03"
          strip={<button type="button">Conditions</button>}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link')).toHaveAttribute('href', '/campaigns/c/casebook?mode=FM-03');
    expect(screen.getByRole('link')).not.toContainElement(screen.getByRole('button'));
  });
});
