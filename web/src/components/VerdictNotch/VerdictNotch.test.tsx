import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { VerdictNotch } from './VerdictNotch';

describe('VerdictNotch', () => {
  it.each(['PASS', 'FAIL', 'INVALID'] as const)(
    'includes the %s word with a unique shape',
    (verdict) => {
      const { container } = render(<VerdictNotch verdict={verdict} />);
      expect(screen.getByText(verdict)).toBeInTheDocument();
      expect(container.querySelector(verdict === 'PASS' ? 'circle' : 'path')).not.toBeNull();
      expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    },
  );
});
