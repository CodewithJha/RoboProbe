import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getKeyboardManager, KeyboardManager, keyboardConfig, registerShortcut } from './keyboard';

function press(target: EventTarget, key: string, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

describe('KeyboardManager', () => {
  let root: HTMLDivElement;
  let manager: KeyboardManager;

  beforeEach(() => {
    vi.useFakeTimers();
    root = document.createElement('div');
    document.body.append(root);
    manager = new KeyboardManager(root);
  });

  afterEach(() => {
    manager.dispose();
    root.remove();
    vi.useRealTimers();
  });

  it('runs single-key shortcuts and prevents the default action', () => {
    const handler = vi.fn();
    manager.register({ keys: '/', handler, description: 'Search' });
    const event = press(root, '/');
    expect(handler).toHaveBeenCalledWith(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it('leaves unbound keys alone', () => {
    manager.register({ keys: 'j', handler: vi.fn(), description: 'Next' });
    expect(press(root, 'x').defaultPrevented).toBe(false);
  });

  it('runs a chord when the second key arrives within the timeout', () => {
    const handler = vi.fn();
    manager.register({ keys: 'g b', handler, description: 'Bench' });
    expect(press(root, 'g').defaultPrevented).toBe(false);
    vi.advanceTimersByTime(keyboardConfig.chordTimeoutMs - 1);
    press(root, 'b');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('drops a pending chord after the timeout', () => {
    const handler = vi.fn();
    manager.register({ keys: 'g b', handler, description: 'Bench' });
    press(root, 'g');
    vi.advanceTimersByTime(keyboardConfig.chordTimeoutMs);
    press(root, 'b');
    expect(handler).not.toHaveBeenCalled();
  });

  it('honours a custom chord timeout', () => {
    manager.dispose();
    manager = new KeyboardManager(root, { chordTimeoutMs: 50 });
    const handler = vi.fn();
    manager.register({ keys: 'g c', handler, description: 'Campaign' });
    press(root, 'g');
    vi.advanceTimersByTime(50);
    press(root, 'c');
    expect(handler).not.toHaveBeenCalled();
  });

  it('falls back to the single key when a chord does not complete', () => {
    const chord = vi.fn();
    const single = vi.fn();
    manager.register({ keys: 'g b', handler: chord, description: 'Bench' });
    manager.register({ keys: 'j', handler: single, description: 'Next' });
    press(root, 'g');
    press(root, 'j');
    expect(chord).not.toHaveBeenCalled();
    expect(single).toHaveBeenCalledOnce();
  });

  it('can start a new chord right after an unmatched one', () => {
    const handler = vi.fn();
    manager.register({ keys: 'g b', handler, description: 'Bench' });
    press(root, 'g');
    press(root, 'g');
    press(root, 'b');
    expect(handler).toHaveBeenCalledOnce();
  });

  it.each([
    ['input', '<input />'],
    ['textarea', '<textarea></textarea>'],
    ['select', '<select><option>a</option></select>'],
    ['contenteditable', '<div contenteditable="true"><span>x</span></div>'],
  ])('ignores typing inside %s', (_name, html) => {
    const handler = vi.fn();
    manager.register({ keys: 'j', handler, description: 'Next' });
    root.innerHTML = html;
    const leaf = root.querySelector('span, input, textarea, select');
    press(leaf ?? root, 'j');
    expect(handler).not.toHaveBeenCalled();
  });

  it('still handles keys in contenteditable="false" regions', () => {
    const handler = vi.fn();
    manager.register({ keys: 'j', handler, description: 'Next' });
    root.innerHTML = '<div contenteditable="false"><span>x</span></div>';
    press(root.querySelector('span') ?? root, 'j');
    expect(handler).toHaveBeenCalledOnce();
  });

  it.each([{ ctrlKey: true }, { metaKey: true }, { altKey: true }])(
    'ignores keys with modifier %j',
    (init) => {
      const handler = vi.fn();
      manager.register({ keys: 'j', handler, description: 'Next' });
      press(root, 'j', init);
      expect(handler).not.toHaveBeenCalled();
    },
  );

  it('accepts shifted characters such as ?', () => {
    const handler = vi.fn();
    manager.register({ keys: '?', handler, description: 'Shortcuts' });
    press(root, '?', { shiftKey: true });
    expect(handler).toHaveBeenCalledOnce();
  });

  it('unregisters and lists shortcuts for the ? dialog', () => {
    const off = manager.register({ keys: ' g  b ', handler: vi.fn(), description: 'Bench' });
    manager.register({ keys: 'r', handler: vi.fn(), scope: 'feature', description: 'Replay' });
    expect(manager.list()).toEqual([
      { keys: 'g b', scope: 'global', description: 'Bench' },
      { keys: 'r', scope: 'feature', description: 'Replay' },
    ]);
    off();
    off();
    expect(manager.list().map((s) => s.keys)).toEqual(['r']);
  });

  it('does not let a stale unregister remove a newer registration', () => {
    const off = manager.register({ keys: 'j', handler: vi.fn(), description: 'Old' });
    off();
    manager.register({ keys: 'j', handler: vi.fn(), description: 'New' });
    off();
    expect(manager.list()).toHaveLength(1);
  });

  it.each([
    ['j', 'j'],
    ['g', 'g b'],
    ['g b', 'g'],
  ])('rejects %j when %j is registered', (existing, next) => {
    manager.register({ keys: existing, handler: vi.fn(), description: 'a' });
    expect(() => manager.register({ keys: next, handler: vi.fn(), description: 'b' })).toThrow(
      /conflicts/,
    );
  });

  it.each(['', '   ', 'g b c'])('rejects malformed keys %j', (keys) => {
    expect(() => manager.register({ keys, handler: vi.fn(), description: 'x' })).toThrow(
      /one key or a two-key chord/,
    );
  });

  it('stops listening after dispose', () => {
    const handler = vi.fn();
    manager.register({ keys: 'j', handler, description: 'Next' });
    manager.dispose();
    press(root, 'j');
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('registerShortcut', () => {
  it('binds to the app-wide manager on document', () => {
    const handler = vi.fn();
    const off = registerShortcut({ keys: 'k', handler, description: 'Previous' });
    expect(getKeyboardManager()).toBe(getKeyboardManager());
    press(document.body, 'k');
    off();
    press(document.body, 'k');
    expect(handler).toHaveBeenCalledOnce();
  });
});
