import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  it('shows caller-owned next-action copy and a navigation action', () => {
    render(
      <MemoryRouter>
        <EmptyState
          title="No campaigns"
          body="Create a campaign to begin testing."
          action={{ label: 'New campaign', to: '/campaigns/new' }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'No campaigns' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'New campaign' })).toHaveAttribute(
      'href',
      '/campaigns/new',
    );
  });
  it('invokes callback actions', () => {
    const retry = vi.fn();
    render(
      <EmptyState title="No data" body="Try again." action={{ label: 'Retry', onClick: retry }} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
