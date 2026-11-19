import { render, screen } from '@testing-library/react';

import { App } from './App';

describe('App', () => {
  it('renders the product heading inside the main landmark', () => {
    render(<App />);

    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'RoboProbe' })).toBeInTheDocument();
  });
});
