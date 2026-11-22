import { fireEvent, render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { Component } from './SettingsPage';

const server = setupServer(
  http.get(apiUrl('/meta'), () => HttpResponse.json({ version: '0.0.0' })),
);

beforeAll(() => {
  server.listen();
});
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
  sessionStorage.clear();
});
afterAll(() => {
  server.close();
});

it('stores the API token in sessionStorage only', () => {
  render(
    <AppProviders live={false}>
      <Component />
    </AppProviders>,
  );
  fireEvent.change(screen.getByLabelText(/Bearer token/i), { target: { value: 'secret-token' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save token' }));
  expect(sessionStorage.getItem('roboprobe.api-token')).toBe('secret-token');
  expect(localStorage.getItem('roboprobe.api-token')).toBeNull();
});
